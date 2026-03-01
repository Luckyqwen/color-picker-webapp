import os
import requests
from flask import Flask, send_file, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
TELEGRAM_API_URL = 'https://api.telegram.org/file/bot{0}/{1}'

@app.route('/photo/<file_id>')
def get_photo(file_id):
    if not BOT_TOKEN:
        return abort(500, 'BOT_TOKEN not set')
    file_url = TELEGRAM_API_URL.format(BOT_TOKEN, file_id)
    resp = requests.get(file_url, stream=True)
    if resp.status_code != 200:
        return abort(resp.status_code)
    return send_file(
        resp.raw,
        mimetype=resp.headers.get('content-type', 'image/jpeg')
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)