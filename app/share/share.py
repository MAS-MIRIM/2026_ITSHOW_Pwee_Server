from flask import Flask, render_template, request, send_file
from dotenv import load_dotenv
import os
from flask_mail import Mail, Message
import qrcode
import re

def qrcode_make(user_name):
    # photo 폴더 내 이미지 확인
    image_path = os.path.join(
        os.getcwd(),
        "static", "images", "photo",
        f"{user_name}.png"
    )
    # 파일 없으면 종료
    if not os.path.exists(image_path):
        return None
    # QR 파일명
    file_name = f"{user_name}_qrcode.png"
    # QR 저장 폴더
    save_dir = os.path.join(
        os.getcwd(),
        "static", "images", "qrcode"
    )

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    save_path = os.path.join(save_dir, file_name)

    # QR에 들어갈 URL **URL은 서버 주소로 변경!**
    qr_data = f"http://192.168.0.10:5000/download/{user_name}"
    # QR 생성
    img = qrcode.make(qr_data)
    # 저장
    img.save(save_path)
    return file_name

app = Flask(__name__)
load_dotenv()

app.config['MAIL_SERVER'] = os.getenv('MAILER_HOST')
app.config['MAIL_PORT'] = int(os.getenv('MAILER_PORT', 465))
app.config['MAIL_USERNAME'] = os.getenv('MAILER_USER')
app.config['MAIL_PASSWORD'] = os.getenv('MAILER_PASS')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAILER_FROM')

app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

app.config['MAIL_DEBUG'] = True

mail = Mail(app)


@app.route('/')
def hello_world():
    return "hello world!"

@app.route('/forms')
def email_form():
    return render_template('test_email.html')

@app.route('/generate/<username>')
def generate_qr(username):
    qr_file = qrcode_make(username)

    if qr_file is None:
        return "이미지가 존재하지 않습니다."

    return render_template('index.html', qr_image=qr_file)

@app.route('/download/<username>')
def download(username):
    image_path = f"static/images/photo/{username}.png"
    return send_file(image_path, mimetype='image/png')


@app.route('/share/<photo>')
def instargram_share(photo):
    return {"image_url": f"https://your-server.com/static/images/photo/{photo}"}


@app.route('/send', methods=['POST'])
def send_email():
    email = request.form.get('email')

    if not email:
        return {"message": "이메일 주소가 필요합니다."}, 400

    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'

    if not re.match(pattern, email):
        return {"message": "이메일 형식 아님"}, 400

    image_path = '../../../static/images/photo/photo_test.png'

    print(os.path.exists(image_path))

    msg = Message(
        subject='사진 공유',
        sender=app.config['MAIL_USERNAME'],
        recipients=[email]
    )

    msg.body = '촬영한 사진입니다.'

    try:
        with app.open_resource(image_path) as fp:
            msg.attach(
                filename='photo_test.png',
                content_type='image/png',
                data=fp.read()
            )

        mail.send(msg)

        return {"message": "메일 전송 완료"}

    except Exception as e:
        print(e)
        return {"message": f"전송 실패: {str(e)}"}, 500