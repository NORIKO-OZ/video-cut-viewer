import os
import sys
import uuid
import subprocess
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, Response, jsonify
from PIL import Image
import tempfile
import shutil
import threading
import time
import json
from collections import defaultdict

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

# 進捗状況を管理するグローバル辞書
progress_data = defaultdict(lambda: {'progress': 0, 'status': 'waiting', 'step': '', 'estimated_time': 0})
progress_lock = threading.Lock()

def update_progress(session_id, progress, status, step, estimated_time=0):
    """進捗情報を更新"""
    with progress_lock:
        progress_data[session_id].update({
            'progress': progress,
            'status': status,
            'step': step,
            'estimated_time': estimated_time,
            'timestamp': time.time()
        })

def extract_scenes_with_ffmpeg(video_path, output_dir, session_id=None):
    """FFmpegを使用してシーン変化を検出してフレームを抽出"""
    os.makedirs(output_dir, exist_ok=True)
    
    if session_id:
        update_progress(session_id, 10, 'processing', 'シーン変化を検出中...', 60)
    
    try:
        # まずシーン検出でタイムスタンプを取得
        scene_timestamps = []
        cmd_detect = [
            'ffmpeg', '-i', video_path,
            '-vf', 'select=gt(scene\\,0.2),showinfo',
            '-f', 'null', '-'
        ]
        
        print("Detecting scene changes...")
        if session_id:
            update_progress(session_id, 20, 'processing', 'シーン変化を解析中...', 45)
        result_detect = subprocess.run(cmd_detect, capture_output=True, text=True, timeout=120)
        
        # showinfo からタイムスタンプを抽出
        import re
        for line in result_detect.stderr.split('\n'):
            if 'showinfo' in line and 'pts_time:' in line:
                match = re.search(r'pts_time:([\d.]+)', line)
                if match:
                    timestamp_sec = float(match.group(1))
                    scene_timestamps.append(timestamp_sec)
        
        print(f"Found {len(scene_timestamps)} scene changes at: {scene_timestamps[:5]}...")
        if session_id:
            update_progress(session_id, 40, 'processing', f'{len(scene_timestamps)}個のシーンを発見', 30)
        
        if not scene_timestamps:
            print("No scene changes detected, using fallback method")
            return []
        
        # 重複を除去し、最小間隔でフィルタリング
        filtered_timestamps = []
        min_interval = 0.5  # 最低0.5秒間隔（重複除去のみ）
        
        for timestamp in sorted(set(scene_timestamps)):  # 重複除去とソート
            if not filtered_timestamps or (timestamp - filtered_timestamps[-1]) >= min_interval:
                filtered_timestamps.append(timestamp)
        
        print(f"After filtering: {len(filtered_timestamps)} unique scenes (min {min_interval}s interval)")
        scene_timestamps = filtered_timestamps
        
        # 0秒のフレームを最初に追加（開始フレーム）
        if not scene_timestamps or scene_timestamps[0] > 0.5:
            scene_timestamps.insert(0, 0.0)
            print("Added 0s frame as starting point")
        
        # 検出された各シーン時刻でフレームを抽出
        scenes_data = []
        total_scenes = len(scene_timestamps)
        for i, timestamp_sec in enumerate(scene_timestamps):
            if session_id:
                progress = 50 + (i / total_scenes) * 40  # 50%から50%で抽出進捗
                update_progress(session_id, progress, 'processing', f'フレーム抽出: {i+1}/{total_scenes}', (total_scenes-i)*2)
            # タイムスタンプをファイル名に含める（重複防止）
            timestamp_int = int(timestamp_sec)
            filename = f'scene_{timestamp_int:04d}s_{i+1:02d}.jpg'
            output_file = os.path.join(output_dir, filename)
            
            cmd_extract = [
                'ffmpeg', '-ss', str(timestamp_sec), '-i', video_path,
                '-vframes', '1', '-q:v', '2', output_file
            ]
            
            result_extract = subprocess.run(cmd_extract, capture_output=True, text=True, timeout=30)
            
            if result_extract.returncode == 0:
                # タイムスタンプをフォーマット
                hours = int(timestamp_sec // 3600)
                minutes = int((timestamp_sec % 3600) // 60)
                seconds = int(timestamp_sec % 60)
                timestamp_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}.000"
                
                scenes_data.append((filename, timestamp_str))
                print(f"Scene {i+1}: {filename} -> {timestamp_str} ({timestamp_sec:.3f}s)")
                if session_id:
                    progress = 50 + ((i+1) / total_scenes) * 40
                    update_progress(session_id, progress, 'processing', f'フレーム抽出完了: {i+1}/{total_scenes}', (total_scenes-i-1)*2)
            else:
                print(f"Failed to extract frame at {timestamp_sec}s")
        
        if session_id:
            update_progress(session_id, 95, 'completing', 'シーン抽出完了', 2)
        return scenes_data
        
    except subprocess.TimeoutExpired:
        print("FFmpeg scene detection timeout")
        return []
    except Exception as e:
        print(f"Error in scene detection: {e}")
        return []

def extract_frames_with_ffmpeg(video_path, output_dir, interval_sec=5, session_id=None):
    """FFmpegを使用してフレームを抽出"""
    os.makedirs(output_dir, exist_ok=True)
    
    if session_id:
        update_progress(session_id, 10, 'processing', '動画情報を取得中...', 30)
    
    try:
        # まず動画の長さを取得
        cmd_duration = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json', 
            '-show_entries', 'format=duration', video_path
        ]
        if session_id:
            update_progress(session_id, 20, 'processing', '動画の長さを調査中...', 25)
        duration_result = subprocess.run(cmd_duration, capture_output=True, text=True, timeout=30)
        
        if duration_result.returncode != 0:
            print(f"FFprobe error: {duration_result.stderr}")
            return []
        
        import json
        duration_data = json.loads(duration_result.stdout)
        video_duration = float(duration_data['format']['duration'])
        if session_id:
            update_progress(session_id, 30, 'processing', f'動画長さ: {int(video_duration)}秒', 20)
        
        # 抽出する時刻のリストを作成
        timestamps = []
        files = []
        frame_count = 0
        total_frames = int(video_duration / interval_sec) + 1
        
        if session_id:
            update_progress(session_id, 40, 'processing', f'{total_frames}個のフレームを抽出予定', 15)
        
        current_time = 0
        while current_time < video_duration:
            frame_count += 1
            
            if session_id:
                progress = 40 + (frame_count / total_frames) * 50  # 40%から50%で抽出進捗
                update_progress(session_id, progress, 'processing', f'フレーム抽出: {frame_count}/{total_frames}', (total_frames-frame_count)*1.5)
            
            # 各時刻でフレームを抽出
            cmd = [
                'ffmpeg', '-ss', str(current_time), '-i', video_path,
                '-vframes', '1', '-q:v', '2',
                os.path.join(output_dir, f'screenshot_{frame_count:03d}.jpg')
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                hours = int(current_time // 3600)
                minutes = int((current_time % 3600) // 60)
                seconds = int(current_time % 60)
                timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}.000"
                timestamps.append(timestamp)
                files.append(f'screenshot_{frame_count:03d}.jpg')
                print(f"Frame {frame_count}: screenshot_{frame_count:03d}.jpg -> {timestamp} ({current_time}秒)")
            else:
                print(f"Failed to extract frame at {current_time}s: {result.stderr}")
            
            current_time += interval_sec
        
        if session_id:
            update_progress(session_id, 95, 'completing', 'フレーム抽出完了', 2)
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

@app.route('/progress/<session_id>')
def get_progress(session_id):
    """進捗情報をServer-Sent Eventsで送信"""
    def generate():
        last_progress = -1
        start_time = time.time()
        
        while True:
            with progress_lock:
                current_data = progress_data.get(session_id, {})
            
            current_progress = current_data.get('progress', 0)
            
            # 進捗が変わったら送信
            if current_progress != last_progress or (time.time() - start_time) > 120:  # 2分でタイムアウト
                data = json.dumps(current_data)
                yield f"data: {data}\n\n"
                last_progress = current_progress
                
                # 完了時は接続終了
                if current_progress >= 100 or current_data.get('status') == 'completed':
                    break
                    
                # タイムアウト時は接続終了
                if (time.time() - start_time) > 120:
                    break
            
            time.sleep(0.5)  # 0.5秒毎にチェック
    
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache',
                           'Connection': 'keep-alive',
                           'Access-Control-Allow-Origin': '*'})

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            print(f"POST request received. Files: {list(request.files.keys())}")
            print(f"Form data: {dict(request.form)}")
            
            if 'video' not in request.files:
                print("No video file in request")
                flash('動画ファイルを選択してください')
                return redirect(request.url), 400
        
            file = request.files['video']
            print(f"Video file: {file.filename}")
            
            if file.filename == '':
                print("Empty filename")
                flash('動画ファイルを選択してください')
                return redirect(request.url), 400
        
            if file:
                # セッションIDを取得または生成
                session_id = request.form.get('session_id')
                if not session_id:
                    session_id = str(uuid.uuid4())
                print(f"Session ID: {session_id}")
                update_progress(session_id, 5, 'uploading', 'ファイルをアップロード中...', 90)
            
                # ファイル保存
                filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                update_progress(session_id, 8, 'uploaded', 'アップロード完了', 80)
            
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
                
                    if mode == 'scene':
                        frame_data = extract_scenes_with_ffmpeg(filepath, scene_dir, session_id)
                    else:
                        frame_data = extract_frames_with_ffmpeg(filepath, scene_dir, interval, session_id)
                    print(f"Frame extraction completed. Result: {len(frame_data) if frame_data else 0} frames")
                    print(f"Frame data format: {frame_data[:2] if frame_data else 'No data'}")
                
                    if not frame_data:
                        # FFmpegが使えない場合の代替処理
                        print("No frames extracted, showing error")
                        if session_id:
                            update_progress(session_id, 0, 'error', 'フレーム抽出失敗', 0)
                        flash('動画の処理に失敗しました。ファイル形式を確認してください。')
                        return redirect(request.url)
                
                    # frame_dataの形式を確認して適切に処理
                    scenes = []
                    for item in frame_data:
                        if isinstance(item, tuple) and len(item) == 2:
                            # (filename, timestamp) 形式
                            fname, timestamp = item
                            scenes.append({
                                'image': f"{filename_no_ext}/{fname}",
                                'start': timestamp
                            })
                        elif isinstance(item, dict):
                            # 辞書形式の場合
                            scenes.append({
                                'image': f"{filename_no_ext}/{item.get('filename', '')}",
                                'start': item.get('time_display', '00:00:00.000')
                            })
                        else:
                            print(f"Unexpected frame_data format: {type(item)} - {item}")
                
                    print(f"Final scenes data: {scenes[:2] if scenes else 'No scenes'}")
                
                    # 処理完了を通知
                    update_progress(session_id, 100, 'completed', '完了', 0)
                    
                    return render_template('index.html', 
                                         video=filename, 
                                         scenes=scenes, 
                                         selected_mode=mode, 
                                         interval=interval,
                                         session_id=session_id)
                                     
                except Exception as e:
                    print(f"処理エラー: {e}")
                    import traceback
                    traceback.print_exc()
                    if session_id:
                        update_progress(session_id, 0, 'error', f'エラー: {str(e)}', 0)
                    flash('動画の処理中にエラーが発生しました')
                    return redirect(request.url), 500
                
        except Exception as e:
            print(f"Request processing error: {e}")
            import traceback
            traceback.print_exc()
            return {'error': str(e)}, 400
    
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

@app.route('/uploads/<filename>')
def serve_uploaded_file(filename):
    """アップロードされた動画ファイルを配信"""
    return send_from_directory(UPLOAD_FOLDER, filename)

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