import os
import sys
import uuid
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory

# パス設定
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

template_folder = os.path.join(base_dir, 'templates')
static_folder = os.path.join(base_dir, 'static')

# フォルダ作成
UPLOAD_FOLDER = os.path.join(base_dir, 'uploads')
SCENES_FOLDER = os.path.join(static_folder, 'scenes')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SCENES_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
app.secret_key = 'your-secret-key-here'

@app.route('/')
def index():
    return render_template('index_minimal.html')

@app.route('/health')
def health():
    return jsonify({'status': 'OK', 'message': 'Application is running'})

@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'video' not in request.files:
            return jsonify({'error': 'No video file uploaded'}), 400
        
        file = request.files['video']
        if file.filename == '':
            return jsonify({'error': 'No video file selected'}), 400
        
        # ファイル保存
        filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        # フレーム抽出を試行
        filename_no_ext = os.path.splitext(filename)[0]
        scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
        
        frames = extract_frames_simple(filepath, scene_dir)
        
        if frames:
            return jsonify({
                'message': 'Video processed successfully',
                'filename': file.filename,
                'frames': len(frames),
                'preview_url': f'/scenes/{filename_no_ext}/{frames[0]}' if frames else None
            })
        else:
            return jsonify({
                'message': 'Video uploaded but processing failed',
                'filename': file.filename,
                'note': 'FFmpeg may not be available on this platform'
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_frames_simple(video_path, output_dir, interval_sec=5):
    """シンプルなフレーム抽出（FFmpegを使用）"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # FFmpegでフレームを抽出
        cmd = [
            'ffmpeg', '-i', video_path,
            '-vf', f'fps=1/{interval_sec}',
            '-q:v', '2',
            '-y',  # overwrite
            os.path.join(output_dir, 'frame_%03d.jpg')
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            # 生成されたファイルを取得
            files = sorted([f for f in os.listdir(output_dir) if f.endswith('.jpg')])
            return files
        else:
            print(f"FFmpeg error: {result.stderr}")
            return []
        
    except subprocess.TimeoutExpired:
        print("FFmpeg timeout")
        return []
    except FileNotFoundError:
        print("FFmpeg not found")
        return []
    except Exception as e:
        print(f"Error extracting frames: {e}")
        return []

@app.route('/scenes/<path:filename>')
def serve_scene(filename):
    return send_from_directory(SCENES_FOLDER, filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)