import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return '''
    <html>
        <head><title>Video Cut Viewer - Simple Test</title></head>
        <body>
            <h1>🎬 Video Cut Viewer</h1>
            <p>Simple test version is running!</p>
            <p>Port: {}</p>
        </body>
    </html>
    '''.format(os.environ.get('PORT', 'Not set'))

@app.route('/health')
def health():
    return {'status': 'OK', 'message': 'Simple test app running'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)