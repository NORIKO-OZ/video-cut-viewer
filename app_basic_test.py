from flask import Flask
import os

app = Flask(__name__)

@app.route('/health')
def health():
    return {'status': 'OK', 'message': 'Basic test app working'}

@app.route('/debug')
def debug():
    return {
        'app': 'app_basic_test.py',
        'port': os.environ.get('PORT', 'Not set'),
        'cwd': os.getcwd()
    }

@app.route('/')
def index():
    return '<h1>Test App Running</h1><p><a href="/health">Health</a> | <a href="/debug">Debug</a></p>'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting test app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)