import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello():
    return '''
    <html>
        <head><title>Video Cut Viewer Test</title></head>
        <body>
            <h1>Hello! Application is running!</h1>
            <p>Port: {}</p>
            <p>Environment: {}</p>
        </body>
    </html>
    '''.format(os.environ.get('PORT', 'Not set'), os.environ.get('RAILWAY_ENVIRONMENT', 'Not Railway'))

@app.route('/health')
def health():
    return {'status': 'OK', 'message': 'Test app running'}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)