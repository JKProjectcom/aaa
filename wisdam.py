import json
import math
import requests
import urllib
import os
import re
import boto3
from boto3.dynamodb.conditions import Attr

def lambda_handler(event, context):
    
    for message_event in json.loads(event['body'])['events']:
        
        user_id = message_event["source"].get("userId")
        group_id = ""
        user_group_id = ""

        url = 'https://api.line.me/v2/bot/message/reply'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + os.environ['CHANNEL_ACCESS_TOKEN'],
        }
        body = {
            'replyToken': message_event['replyToken'],
            'messages': []
        }
        
        type = message_event["type"]
        
        if type=="message":
            # メッセージが送信された場合
            msg_text = message_event["message"]["text"]
            
            if msg_text == "クイズメニュー":
                body["messages"] = create_menu_button()
            elif msg_text == "設定変更":
                body["messages"] = create_setting_button()
            else:
                if get_data(user_id).get("quiz_state") == "change_theme":
                    update_data(user_id, {"theme": msg_text, "quiz_state": "neutral"})
                    body["messages"] = create_menu_button("クイズテーマを" + msg_text + "に変更しました。")
                
        elif type == "postback":
            print("ポストバック")
            # ボタン押下された場合
            postback_data = message_event.get("postback").get("data")
            if postback_data == "quiz_menu":
                # クイズメニューへが押された場合
                body["messages"] = create_menu_button()
                
            elif postback_data == "start_quiz":
                # クイズ出題が押された場合
                print("クイズ出題")
                body["messages"] = create_quiz_button(user_id)

            elif postback_data == "change_quiz_theme":
                # クイズテーマ変更が押された場合
                update_data(user_id, {"quiz_state": "change_theme"})
                body["messages"] = reply_message("テーマを入力してください。")
                
            elif postback_data == "change_quiz_type":
                # 出題形式変更が選択された場合
                body["messages"] = create_setting_button()
                
            elif postback_data == "T/F":
                # ○×が押された場合
                update_data(user_id, {"quiz_type": "T/F"})
                body["messages"] = create_menu_button("○×形式に変更しました。")
            
            elif postback_data == "4_choices":
                # 4択が押された場合
                update_data(user_id, {"quiz_type": "4_choices"})
                body["messages"] = create_menu_button("4択形式に変更しました。")
                
            elif postback_data == "grades":
                # 成績が選択された場合
                user_grades = get_user_grades(user_id)
                body["messages"] = create_user_grades_button(user_grades)
                
            elif postback_data == "reset_grades":
                # 成績をリセットするが押された場合
                reset_msg = reset_grades(user_id)
                body["messages"] = create_menu_button(reset_msg)

            elif postback_data.startswith("T") or postback_data.startswith("F"):
                # ○×クイズの選択肢が選択された場合
                print("まるばつ："+postback_data)
                answer_explanation = correct_answer_announcement_tf(user_id, postback_data)
                body["messages"] = create_next_quiz(answer_explanation)
                
            elif postback_data.startswith("4"):
                # 4択クイズの選択肢が選択された場合
                print("４たく："+postback_data)
                answer_explanation = correct_answer_announcement_4_choices(user_id, postback_data)
                body["messages"] = create_next_quiz(answer_explanation)
                
            elif postback_data == "back_to_menu":
                # 戻るが選択された場合
                body["messages"] = create_menu_button()
        
        try:
            request_data = json.dumps(body).encode('utf-8')
            response = requests.post(url,headers=headers,data=request_data)
            print("ステータスコード："+str(response.status_code))
        
        except Exception as e:
            print("エラー発生:" + str(e))
            
    return {
        'statusCode': 200,
    }

def reply_message(msg):
    return [
        {
            "type": "text",
            "text": msg,
        }
    ]

# クイズメニューが押下されたときに表示するボタン
def create_menu_button(msg = "クイズメニュー"):
    return [
        {
            "type": "template",
            "altText": "menu",
            "template": {
                "type": "buttons",
                # "title": "クイズメニュー",
                "text": msg,
                "actions": [
                    {
                        "type": "postback",
                        "label": "クイズ出題",
                        "displayText": "クイズ出題",
                        "data": "start_quiz",
                    },
                    {
                        "type": "postback",
                        "label": "クイズテーマ変更",
                        "displayText": "クイズテーマ変更",
                        "inputOption": "openKeyboard",
                        "data": "change_quiz_theme",
                    },
                    {
                        "type": "postback",
                        "label": "出題形式変更",
                        "displayText": "出題形式変更",
                        "data": "change_quiz_type",
                    },
                    {
                        "type": "postback",
                        "label": "成績",
                        "displayText": "成績",
                        "data": "grades",
                    },
                ],
            },
        },
    ]
    
# クイズの出題形式を変更するボタン
def create_setting_button():
    return [
        {
            "type": "template",
            "altText": "setting",
            "template": {
                "type": "buttons",
                "title": "設定",
                "text": "クイズの出題形式を変更できます。",
                "actions": [
                    {
                        "type": "postback",
                        "label": "○×",
                        "displayText": "○×",
                        "data": "T/F",
                    },
                    {
                        "type": "postback",
                        "label": "4択",
                        "displayText": "4択",
                        "data": "4_choices",
                    },
                ],
            },
        },
    ]
    
# クイズ出題が押下されたときクイズを作成して表示する    
def create_quiz_button(user_id):
    
    # 設定されているテーマと出題形式を取得する。未設定の場合はランダムと○×にする。
    quiz_theme = "ランダム"
    quiz_type = "T/F"
    user_data = get_data(user_id)
    if user_data:
        user_theme = user_data.get("theme")
        if user_theme:
            quiz_theme = user_theme
            
        user_type = user_data.get("quiz_type")
        if user_type:
            quiz_type = user_type
    
    # テーマをもとにクイズを作成する
    quiz_text = request_open_ai_quiz(quiz_theme, quiz_type)

    # 作成されたクイズから問題・答え・解説を抽出する
    if quiz_type == "T/F":
        return create_tf_quiz(user_id, quiz_theme, quiz_text)
    else:
        return create_4_choices_quiz(user_id, quiz_theme, quiz_text)
        
# クイズ解答後の次の問題のためのボタン
def create_next_quiz(answer_explanation):
    answer = answer_explanation.get("answer")
    explanation = answer_explanation.get("explanation")
    print("ooooo answer:" + answer)
    print("ooooo ex:" + explanation)
    return [
        {
            "type": "template",
            "altText": "nextmenu",
            "template": {
                "type": "buttons",
                "title": "正解は" + answer,
                "text": explanation,
                "actions": [
                    {
                        "type": "postback",
                        "label": "次のクイズへ",
                        "displayText": "次のクイズへ",
                        "data": "start_quiz",
                    },
                    {
                        "type": "postback",
                        "label": "クイズテーマ変更",
                        "displayText": "クイズテーマ変更",
                        "inputOption": "openKeyboard",
                        "data": "change_quiz_theme",
                    },
                    {
                        "type": "postback",
                        "label": "クイズメニューへ",
                        "displayText": "クイズメニューへ",
                        "data": "quiz_menu",
                    },
                ],
            },
        },
    ]

# chat-GPTから返ってきた文章から○×クイズの形式で使えるように加工する 
def create_tf_quiz(user_id, quiz_theme, quiz_text):
    
    replaced_text = re.sub("[\s\n]", "", quiz_text)

    # 問題と答えと解説部分を切り離す
    question = ""
    question = search_text(replaced_text, r"問題:(.*?)答え")
    
    answer = ""
    answer = search_text(replaced_text, r"答え:(.*?)解説")
    
    explanation = ""
    explanation = search_text(replaced_text, r"解説:(.*)")

    # 問題と答えと解説が切り離せたら保存する
    if question and answer and explanation:
        update_data(user_id, {"question": question, "answer": answer, "explanation": explanation})

    # ボタン
    button_obj = [
        {
            "type": "template",
            "altText": "○×クイズ",
            "template": {
                "type": "buttons",
                "title": quiz_theme,
                "text": question,
                "actions": [
                    {
                        "type": "postback",
                        "label": "○",
                        "displayText": "○",
                        "data": "",
                    },
                    {
                        "type": "postback",
                        "label": "×",
                        "displayText": "×",
                        "data": "",
                    },
                ],
            },
        }
    ]
    
    # 選択肢に正解不正解を設定する
    if "t" in answer or "T" in answer:
        button_obj[0]["template"]["actions"][0]["data"] = "T○"
        button_obj[0]["template"]["actions"][1]["data"] = "F○"
    else:
        button_obj[0]["template"]["actions"][0]["data"] = "F×"
        button_obj[0]["template"]["actions"][1]["data"] = "T×"
        
    return button_obj

# chat-GPTから返ってきた文章から4択クイズの形式で使えるように加工する     
def create_4_choices_quiz(user_id, quiz_theme, quiz_text):
    
    replaced_text = re.sub("[\s\n]", "", quiz_text)

    # 問題と選択肢と答えと解説部分を切り離す
    question = ""
    question = search_text(replaced_text, r"問題:(.*?)選択肢")
    
    choices = ""
    choices = search_text(replaced_text, r"選択肢:(.*?)答え")    
    
    choices_list = []    
    if choices:
        # 選択肢を4つに分解して問題文の末尾に追加
        choice_a = "A." + search_text(choices, r"A\.(.*?)B\.") 
        choice_b = "B." + search_text(choices, r"B\.(.*?)C\.") 
        choice_c = "C." + search_text(choices, r"C\.(.*?)D\.") 
        choice_d = "D." + search_text(choices, r"D\.(.*)") 
        
        question += "\r\n" + choice_a + "\r\n" + choice_b + "\r\n" + choice_c + "\r\n" + choice_d
    
    answer = ""
    answer = search_text(replaced_text, r"答え:(.*?)解説") 
    
    explanation = ""
    explanation = search_text(replaced_text, r"解説:(.*)")

    # 問題と選択肢と答えと解説が切り離せたら保存する
    if question and choices and answer and explanation:
        update_data(user_id, {"question": question, "answer": answer, "explanation": explanation})

    # ボタン
    button_obj = [
        {
            "type": "template",
            "altText": "4択クイズ",
            "template": {
                "type": "buttons",
                "title": quiz_theme,
                "text": question,
                "actions": [
                    {
                        "type": "postback",
                        "label": "A",
                        "displayText": "A",
                        "data": "",
                    },
                    {
                        "type": "postback",
                        "label": "B",
                        "displayText": "B",
                        "data": "",
                    },
                    {
                        "type": "postback",
                        "label": "C",
                        "displayText": "C",
                        "data": "",
                    },
                    {
                        "type": "postback",
                        "label": "D",
                        "displayText": "D",
                        "data": "",
                    },
                ],
            },
        }
    ]
    
    # 選択肢に正解不正解を設定する
    if answer in choice_a:
        set_choices_data(button_obj[0]["template"]["actions"], 0, answer)
    elif answer in choice_b:
        set_choices_data(button_obj[0]["template"]["actions"], 1, answer)
    elif answer in choice_c:
        set_choices_data(button_obj[0]["template"]["actions"], 2, answer)
    elif answer in choice_d:
        set_choices_data(button_obj[0]["template"]["actions"], 3, answer)
        
    return button_obj

# 4択ボタンの選択肢に正解と不正解を設定する  
def set_choices_data(actions, correct_number, answer):
    for i, action in enumerate(actions):
        if i == correct_number:
            action["data"] = "4T" + answer
        else:
            action["data"] = "4F" + answer

# 成績を表示するボタン
def create_user_grades_button(user_grades):
    return [
        {
            "type": "template",
            "altText": "成績",
            "template": {
                "type": "buttons",
                "title": "正解数/出題数（正答率）",
                "text": user_grades,
                "actions": [
                    {
                        "type": "postback",
                        "label": "成績をリセットする",
                        "displayText": "成績をリセットする",
                        "data": "reset_grades",
                    },
                    {
                        "type": "postback",
                        "label": "戻る",
                        "displayText": "戻る",
                        "data": "back_to_menu",
                    },
                ],
            },
        },
    ]

def createData(user_id):
    table = boto3.resource("dynamodb").Table("wisdam_line")
    table.put_item(
    	Item={
    		"user_id": user_id,
    		"correct_answer": "B",
    	}
    )
    
def get_data(user_id):
    table = boto3.resource("dynamodb").Table("wisdam_line")
    try:
        response = table.get_item(
            Key={
                "user_id": user_id
            }
        )
        item = response["Item"]
        return item
        
    except Exception as e:
        return ""

# 設定されているテーマを取得する。未設定の場合はランダムを返す。
def get_user_theme(user_id):
    user_data = get_data(user_id)
    if not user_data:
        return "ランダム"
    
    user_theme = user_data.get("theme")
    if not user_theme:
        return "ランダム"
    
    return user_theme

# クイズの答えを返す    
def get_correct_answer(user_id, group_id):
    if not group_id:
        return get_data(user_id)["correct_answer"]
    else:
        return get_data(group_id)["correct_answer"]
    
# グループに所属していてクイズに参加する人数を返す
def get_participants_count(group_id):
    count = 0
    group_users = get_multi_data("group_id", group_id)
    for user in group_users:
        if user["participate"]:
            count += 1
            
    return count

# グループでクイズに参加している全員が解答した場合Trueを返す   
def check_everyone_answered(group_id):
    group_users = get_multi_data("group_id", group_id)
    for user in group_users:
        if user["participate"] and not user["choice"]:
            return False
    
    return True
    
# 正解発表。正解と解説を返す。○×用。
def correct_answer_announcement_tf(user_id, select_data):
    update_obj = {}
    # 解説を取得
    user_data = get_data(user_id)
    explanation = user_data["explanation"]

    # 正解か不正解か判定
    if select_data.startswith("T"):
        # 正解の場合出題数と正解数をプラス1する
        update_obj["quiz_count"] = user_data.get("quiz_count", 0) + 1
        update_obj["correct_count"] = user_data.get("correct_count", 0) + 1
    
    else:
        # 不正解の場合出題数をプラス1する
        update_obj["quiz_count"] = user_data.get("quiz_count", 0) + 1
        
    update_data(user_id, update_obj)
    
    answer = select_data[1:] # 先頭にT/F、2文字目以降に正解の選択肢が入っているため。
    return {"answer": answer, "explanation": explanation}
    
# 正解発表。正解と解説を返す。4択用。
def correct_answer_announcement_4_choices(user_id, select_data):
    update_obj = {}
    # 解説を取得
    user_data = get_data(user_id)
    explanation = user_data["explanation"]

    # 正解か不正解か判定
    if select_data.startswith("4T"):
        # 正解の場合出題数と正解数をプラス1する
        update_obj["quiz_count"] = user_data.get("quiz_count", 0) + 1
        update_obj["correct_count"] = user_data.get("correct_count", 0) + 1
    
    else:
        # 不正解の場合出題数をプラス1する
        update_obj["quiz_count"] = user_data.get("quiz_count", 0) + 1
        
    update_data(user_id, update_obj)
    
    answer = select_data[2:] # 先頭にT/F、2文字目以降に正解の選択肢が入っているため。
    return {"answer": answer, "explanation": explanation}
    
# 不正解した場合の処理。解説を返す。
def incorrect_answer(user_id):
    update_obj = {}
    # 保存されている情報を取得
    user_data = get_data(user_id)
    explanation = user_data["explanation"]
    # 出題数をプラス1する
    update_obj["quiz_count"] = user_data.get("quiz_count", 0) + 1
        
    update_data(user_id, update_obj)
    
    return explanation

# クイズの成績（出題数と正解数と正答率）を取得する
def get_user_grades(user_id):
    user_data = get_data(user_id)
    quiz_count = user_data.get("quiz_count") if user_data.get("quiz_count") else 0
    correct_count = user_data.get("correct_count") if user_data.get("correct_count") else 0
    answer_ratio = 0
    if quiz_count != 0 and correct_count != 0:
        answer_ratio = math.floor((correct_count / quiz_count) * 100)
        
    user_grades = str(correct_count) + "/" + str(quiz_count) + "（" + str(answer_ratio) + "%）"
    
    return user_grades
    
# クイズの成績をリセットする
def reset_grades(user_id):
    update_data(user_id, {"quiz_count": 0, "correct_count": 0})
    
    return "クイズの成績をリセットしました"

# クイズ終了時クイズの成績を返す    
def get_result(user_id, group_id):
    result_msg = ""

    if not group_id:
        user_data = get_data(user_id)
        user_point = user_data["point"]
        user_quiz_count = user_data["quiz_count"]
        result_msg = "正解数/出題数" + "\r\n" + str(user_point) + "/" + str(user_quiz_count)
    else:
        group_data = get_data(group_id)
        group_quiz_count = group_data["quiz_count"]
        group_user_data = get_multi_data("group_id", group_id)
        result_msg = "名前：正解数/出題数"
        for data in group_user_data:
            user_result = "\r\n" + data["user_name"] + "：" + str(data["point"]) + "/" + str(group_quiz_count)
            result_msg += user_result
    
    return result_msg
    
# クイズ終了後の処理
def finish_quiz_process(user_id, group_id):
    update_obj = {"choice": "", "correct_answer": "", "participate": False, "point": 0, "quiz_count": 0, "quiz_state": "finished_quiz", "theme": ""}
    if not group_id:
        update_data(user_id, update_obj)
    else:
        group_user_list = []
        group_data = get_multi_data("group_id", group_id)
        for data in group_data:
            group_user_list.append(data["user_id"])
        
        for group_user_id in group_user_list:
            update_data(group_user_id, update_obj)
        

# 複数のレコードを取得する   
def get_multi_data(column_name, value):
    table = boto3.resource("dynamodb").Table("wisdam_line")
    column = column_name
    data = value
    
    response = table.scan(
        FilterExpression = Attr(column).eq(data)
    )
    items = response["Items"]
    return items

# データを更新する   
def update_data(user_id, update_info_dict):
    table = boto3.resource("dynamodb").Table("wisdam_line")
    
    update_expression_str = "SET"
    expression_attribute_values_dict = {}
    for key, value in update_info_dict.items():
        placeholder = ":" + key
        update_expression_str += " " + key + " = " + placeholder + ","
        expression_attribute_values_dict[placeholder] = value
    
    update_expression_str = update_expression_str.rstrip(",")

    table.update_item(
        Key = {"user_id": user_id},
        UpdateExpression = update_expression_str,
        ExpressionAttributeValues = expression_attribute_values_dict,
    )

# ステータスを更新する
def updateState(user_id, group_id, state):
    update_info_dict = {"quiz_state": state}
    if group_id:
        update_data(group_id, update_info_dict)
    else:
        update_data(user_id, update_info_dict)

# textからpatternに合致する文字列を切り取って返す      
def search_text(text, pattern):
    result = ""
    match = re.search(pattern, text)
    if match:
        result = match.group(1)
        
    return result

# OpenAiへクイズ作成依頼        
def request_open_ai_quiz(theme, quiz_type):
    API_KEY = os.environ['OPEN_AI_TOKEN']
    API_URL = 'https://api.openai.com/v1/chat/completions'
    content_text = ""
    
    if quiz_type == "T/F":
        if theme == "ランダム":
            content_text = "特殊なテーマでT/Fクイズを1つだけ作成し、短めの分量で、以下の形式で出力してください。問題:答え:解説:"
        else:
            content_text = theme + "に関するT/Fクイズを1つだけ作成し、短めの分量で、以下の形式で出力してください。問題:答え:解説:"
    elif quiz_type == "4_choices":
        if theme == "ランダム":
            content_text = "特殊なテーマで4択クイズを1つだけ作成し、短めの分量で、以下の形式で出力してください。問題:選択肢:A.B.C.D.答え:解説:"
        else:
            content_text = theme + "に関する4択クイズを1つだけ作成し、短めの分量で、以下の形式で出力してください。問題:選択肢:A.B.C.D.答え:解説:"
    
    headers = {
        'Authorization': 'Bearer ' + API_KEY,
        'Content-Type': 'application/json'
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            { 
                "role": "user",
                "content": content_text
            }
        ]
    }
    
    result = ""
    json_list = []
    error_list = []
    response = requests.post(API_URL,headers=headers,data=json.dumps(data).encode('utf-8'))
    return json.loads(response.text)["choices"][0]["message"]["content"]
