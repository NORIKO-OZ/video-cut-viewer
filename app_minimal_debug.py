import os
import sys
import uuid
import subprocess
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from PIL import Image
import tempfile
import shutil
import json

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
    """FFmpegを使用してフレームを抽出（シンプル版）"""
    print(f"=== EXTRACT FRAMES DEBUG ===")
    print(f"Video path: {video_path}")
    print(f"Output dir: {output_dir}")
    print(f"Interval: {interval_sec}")
    print(f"Video exists: {os.path.exists(video_path)}")
    
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"Output directory created: {os.path.exists(output_dir)}")
    except Exception as e:
        print(f"Failed to create output directory: {e}")
        return []
    
    # FFmpeg可用性チェック
    try:
        ffmpeg_check = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        print(f"FFmpeg available: {ffmpeg_check.returncode == 0}")
    except Exception as e:
        print(f"FFmpeg check failed: {e}")
        return []
    
    # 動画の長さを取得
    try:
        cmd_duration = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_entries', 'format=duration', video_path]
        duration_result = subprocess.run(cmd_duration, capture_output=True, text=True, timeout=30)
        
        if duration_result.returncode != 0:
            print(f"FFprobe failed: {duration_result.stderr}")
            return []
        
        duration_data = json.loads(duration_result.stdout)
        video_duration = float(duration_data['format']['duration'])
        print(f"Video duration: {video_duration} seconds")
    except Exception as e:
        print(f"Duration extraction failed: {e}")
        return []
    
    # フレーム抽出
    files = []
    timestamps = []
    current_time = 0
    frame_count = 0
    
    while current_time < video_duration:
        frame_count += 1
        output_file = os.path.join(output_dir, f'screenshot_{frame_count:03d}.jpg')
        
        cmd = ['ffmpeg', '-ss', str(current_time), '-i', video_path, '-vframes', '1', '-q:v', '2', output_file]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(output_file):
                hours = int(current_time // 3600)
                minutes = int((current_time % 3600) // 60)
                seconds = int(current_time % 60)
                timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}.000"
                
                files.append(f'screenshot_{frame_count:03d}.jpg')
                timestamps.append(timestamp)
                print(f"Extracted frame {frame_count}: {timestamp}")
            else:
                print(f"Failed frame extraction at {current_time}s: {result.stderr}")
        except Exception as e:
            print(f"Exception during frame extraction: {e}")
        
        current_time += interval_sec
        
        if frame_count >= 10:  # 最大10フレームで制限
            break
    
    print(f"=== EXTRACTION COMPLETE ===")
    print(f"Total frames extracted: {len(files)}")
    return list(zip(files, timestamps))

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        print("=== POST REQUEST DEBUG ===")
        
        if 'video' not in request.files:
            print("No video file in request")
            flash('動画ファイルを選択してください')
            return redirect(request.url)
        
        file = request.files['video']
        print(f"File received: {file.filename}")
        
        if file.filename == '':
            print("Empty filename")
            flash('動画ファイルを選択してください')
            return redirect(request.url)
        
        if file:
            # ファイル保存
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            print(f"File saved: {filepath}, size: {os.path.getsize(filepath)}")
            
            # 処理モード
            mode = request.form.get('mode', 'interval')
            interval = int(request.form.get('interval', 5))
            print(f"Mode: {mode}, Interval: {interval}")
            
            filename_no_ext = os.path.splitext(filename)[0]
            scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
            
            # フレーム抽出
            try:
                if mode == 'scene':
                    # シーン検出はシンプル版では省略
                    frame_data = []
                    flash('シーン検出モードは現在利用できません')
                else:
                    frame_data = extract_frames_with_ffmpeg(filepath, scene_dir, interval)
                
                print(f"Frame extraction result: {len(frame_data)} frames")
                
                if not frame_data:
                    flash('動画の処理に失敗しました')
                    return redirect(request.url)
                
                # シーンデータ作成
                scenes = []
                for fname, timestamp in frame_data:
                    scenes.append({
                        'image': f"{filename_no_ext}/{fname}",
                        'start': timestamp
                    })
                
                print(f"Final scenes: {len(scenes)}")
                return render_template('index.html', video=filename, scenes=scenes, selected_mode=mode, interval=interval)
                
            except Exception as e:
                print(f"Processing error: {e}")
                import traceback
                traceback.print_exc()
                flash(f'エラー: {str(e)}')
                return redirect(request.url)
    
    return render_template('index.html', video=None, scenes=None, selected_mode='interval')

@app.route('/health')
def health():
    return {'status': 'OK', 'message': 'Minimal debug app running'}

@app.route('/debug')
def debug():
    """システム情報とFFmpeg状態のデバッグ"""
    debug_info = {
        'app_name': 'app_minimal_debug.py',
        'current_directory': os.getcwd(),
        'upload_folder': UPLOAD_FOLDER,
        'scenes_folder': SCENES_FOLDER,
        'upload_exists': os.path.exists(UPLOAD_FOLDER),
        'scenes_exists': os.path.exists(SCENES_FOLDER),
    }
    
    # FFmpegチェック
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        debug_info['ffmpeg_available'] = result.returncode == 0
        debug_info['ffmpeg_version'] = result.stdout.split('\n')[0] if result.returncode == 0 else 'Failed'
    except Exception as e:
        debug_info['ffmpeg_available'] = False
        debug_info['ffmpeg_error'] = str(e)
    
    return debug_info

@app.route('/uploads/<filename>')
def serve_uploaded_file(filename):
    """アップロードされた動画ファイルを配信"""
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/static/scenes/<path:filename>')
def serve_scene_file(filename):
    """抽出されたシーン画像を配信"""
    return send_from_directory(SCENES_FOLDER, filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting minimal debug app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)