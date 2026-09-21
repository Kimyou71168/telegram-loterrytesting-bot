import os  
from flask import Flask, request  
import telebot  
  
TOKEN = '8961460379:AAFO-Qszn24e-upnZVHCjQyj6hKcMpTZQu4'  
bot = telebot.TeleBot(TOKEN)  
  
app = Flask(__name__)  
  
@app.route('/')  
def index():  
    return "Bot status: Active"  
  
@app.route(f'/{TOKEN}', methods=['POST'])  
def webhook():  
    json_string = request.get_data().decode('utf-8')  
    update = telebot.types.Update.de_json(json_string)  
    bot.process_new_updates([update])  
    return "!", 200  
  
if __name__ == '__main__':  
    port = int(os.environ.get('PORT', 5000))  
    app.run(host='0.0.0.0', port=port)  
