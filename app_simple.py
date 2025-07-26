import os
import sys
import uuid
import subprocess
from flask import Flask, render_template, request, redirect, url_for, flash
from PIL import Image
import tempfile
import shutil

if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

template_folder = os.path.join(base_dir, 'templates')
static_folder = os.path.join(base_dir, 'static')

UPLOAD_FOLDER = os.path.join(base_dir, 'uploads')
SCENES_FOLDER = os.path.join(static_folder, 'scenes')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SCENES_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
app.secret_key = 'your-secret-key-here'

def extract_frames_with_ffmpeg(video_path, output_dir, interval_sec=5):
    """FFmpegを使用してフレームを抽出"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # FFmpegでフレームを抽出
        cmd = [
            'ffmpeg', '-i', video_path,
            '-vf', f'fps=1/{interval_sec}',
            '-q:v', '2',  # 高品質
            os.path.join(output_dir, 'screenshot_%03d.jpg')
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print(f"FFmpeg error: {result.stderr}")
            return []
        
        # 生成されたファイルを取得
        files = sorted([f for f in os.listdir(output_dir) if f.endswith('.jpg')])
        timestamps = []
        
        for i, filename in enumerate(files):
            timestamp_seconds = i * interval_sec
            hours = int(timestamp_seconds // 3600)
            minutes = int((timestamp_seconds % 3600) // 60)
            seconds = int(timestamp_seconds % 60)
            # より正確な時間表示のため、実際の秒数を保持
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}.000"
            timestamps.append(timestamp)
            
        return list(zip(files, timestamps))
        
    except subprocess.TimeoutExpired:
        print("FFmpeg timeout")
        return []
    except Exception as e:
        print(f"Error extracting frames: {e}")
        return []

def seconds_to_timecode(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'video' not in request.files:
            flash('動画ファイルを選択してください')
            return redirect(request.url)
        
        file = request.files['video']
        if file.filename == '':
            flash('動画ファイルを選択してください')
            return redirect(request.url)
        
        if file:
            # ファイル保存
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # 処理モードとパラメータ取得
            mode = request.form.get('mode', 'interval')
            interval = int(request.form.get('interval', 5))
            
            filename_no_ext = os.path.splitext(filename)[0]
            scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
            
            print(f"処理モード: {mode}")
            print(f"間隔: {interval}秒")
            
            # フレーム抽出（FFmpegまたはシンプルな方法を使用）
            try:
                print(f"Starting frame extraction for: {filename}")
                print(f"File size: {os.path.getsize(filepath)} bytes")
                
                frame_data = extract_frames_with_ffmpeg(filepath, scene_dir, interval)
                print(f"Frame extraction completed. Result: {len(frame_data) if frame_data else 0} frames")
                
                if not frame_data:
                    # FFmpegが使えない場合の代替処理
                    print("No frames extracted, showing error")
                    flash('動画の処理に失敗しました。ファイル形式を確認してください。')
                    return redirect(request.url)
                
                scenes = [{
                    'image': f"{filename_no_ext}/{fname}",
                    'start': timestamp
                } for fname, timestamp in frame_data]
                
                return render_template('index.html', 
                                     video=filename, 
                                     scenes=scenes, 
                                     selected_mode=mode, 
                                     interval=interval)
                                     
            except Exception as e:
                print(f"処理エラー: {e}")
                flash('動画の処理中にエラーが発生しました')
                return redirect(request.url)
    
    return render_template('index.html', video=None, scenes=None, selected_mode='interval')

@app.route('/health')
def health():
    return {'status': 'OK', 'message': 'Application is running', 'app': 'app_simple.py'}

@app.route('/debug')
def debug():
    """システム情報とFFmpeg状態のデバッグ"""
    import os
    
    debug_info = {
        'app_name': 'app_simple.py',
        'environment_variables': {
            'PATH': os.environ.get('PATH', 'Not set'),
            'PORT': os.environ.get('PORT', 'Not set'),
        },
        'current_directory': os.getcwd(),
        'directory_contents': os.listdir('.') if os.path.exists('.') else 'Cannot list directory',
        'ffmpeg_check': 'Use subprocess to check FFmpeg availability'
    }
    
    # FFmpegの簡単チェック
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        debug_info['ffmpeg_available'] = result.returncode == 0
        debug_info['ffmpeg_version'] = result.stdout.split('\n')[0] if result.returncode == 0 else 'Failed'
    except Exception as e:
        debug_info['ffmpeg_available'] = False
        debug_info['ffmpeg_error'] = str(e)
    
    return debug_info

@app.route('/test')
def test():
    """シンプルなテスト用エンドポイント"""
    return {
        'status': 'OK',
        'message': 'Test endpoint working',
        'timestamp': str(subprocess.run(['date'], capture_output=True, text=True).stdout.strip())
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)