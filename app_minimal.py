import os
import sys
import uuid
import subprocess
import tempfile
import shutil
from flask import Flask, render_template, request, jsonify, send_from_directory
from PIL import Image

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

@app.route('/debug')
def debug():
    """システム情報とFFmpeg状態のデバッグ"""
    import os
    
    debug_info = {
        'environment_variables': {
            'PATH': os.environ.get('PATH', 'Not set'),
            'PORT': os.environ.get('PORT', 'Not set'),
        },
        'ffmpeg_status': check_ffmpeg_availability(),
        'current_directory': os.getcwd(),
        'directory_contents': os.listdir('.') if os.path.exists('.') else 'Cannot list directory'
    }
    
    # システムコマンドでFFmpegを検索
    try:
        find_result = subprocess.run(['find', '/usr', '-name', 'ffmpeg', '-type', 'f'], 
                                   capture_output=True, text=True, timeout=10)
        debug_info['find_ffmpeg'] = find_result.stdout.strip().split('\n') if find_result.stdout.strip() else 'Not found'
    except:
        debug_info['find_ffmpeg'] = 'Command failed'
    
    return jsonify(debug_info)

@app.route('/test-scene-detection')
def test_scene_detection():
    """シーン検出機能のテスト"""
    try:
        # テスト用の小さな動画ファイルを想定
        test_video = "/tmp/test.mp4"  # 存在しないファイルでテスト
        test_output = "/tmp/test_scenes"
        
        # まずffprobeのテスト
        probe_cmd = ['ffprobe', '-version']
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        
        result = {
            'ffprobe_available': probe_result.returncode == 0,
            'ffprobe_version': probe_result.stdout.split('\n')[0] if probe_result.returncode == 0 else 'Failed',
            'ffprobe_error': probe_result.stderr if probe_result.returncode != 0 else None,
        }
        
        # FFmpegのシーンフィルターテスト
        try:
            scene_test_cmd = ['ffmpeg', '-f', 'lavfi', '-i', 'testsrc=duration=10:size=320x240:rate=1', 
                             '-vf', 'select=gt(scene\\,0.3),showinfo', '-vsync', 'vfr', '-f', 'null', '-']
            scene_test_result = subprocess.run(scene_test_cmd, capture_output=True, text=True, timeout=15)
            
            result['scene_filter_test'] = {
                'return_code': scene_test_result.returncode,
                'stderr_length': len(scene_test_result.stderr),
                'contains_showinfo': 'showinfo' in scene_test_result.stderr,
                'contains_pts_time': 'pts_time' in scene_test_result.stderr,
                'stderr_sample': scene_test_result.stderr[:500] if scene_test_result.stderr else 'No stderr'
            }
        except Exception as e:
            result['scene_filter_test'] = {'error': str(e)}
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)})

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
        
        # 処理モードを取得
        mode = request.form.get('mode', 'interval')
        interval = int(request.form.get('interval', 5))
        sensitivity = float(request.form.get('sensitivity', 0.15))
        
        print(f"Processing mode: {mode}, interval: {interval}s, sensitivity: {sensitivity}")
        
        # フレーム抽出
        filename_no_ext = os.path.splitext(filename)[0]
        scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
        
        if mode == 'scene':
            frames = extract_scenes_with_ffmpeg(filepath, scene_dir, sensitivity)
            processing_method = 'scene detection'
        else:
            frames = extract_frames_simple(filepath, scene_dir, interval)
            processing_method = f'interval extraction ({interval}s)'
        
        if frames:
            return jsonify({
                'message': f'Video processed successfully using {processing_method}',
                'filename': file.filename,
                'video_file': filename,
                'frames': len(frames),
                'preview_url': f'/static/scenes/{filename_no_ext}/{frames[0]}',
                'processing_method': processing_method
            })
        else:
            return jsonify({
                'message': 'Video uploaded but processing failed',
                'filename': file.filename,
                'video_file': filename,
                'note': 'Video processing is not available on this platform'
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_frames_simple(video_path, output_dir, interval_sec=5):
    """シンプルなフレーム抽出"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # FFmpegで定間隔フレーム抽出
        output_pattern = os.path.join(output_dir, 'frame_%03d.jpg')
        cmd = [
            'ffmpeg', '-i', video_path,
            '-vf', f'fps=1/{interval_sec}',
            '-q:v', '2',
            '-y',  # overwrite
            output_pattern
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            files = sorted([f for f in os.listdir(output_dir) if f.endswith('.jpg')])
            print(f"Successfully extracted {len(files)} frames")
            return files
        else:
            print(f"FFmpeg error: {result.stderr}")
            return []
        
    except Exception as e:
        print(f"Frame extraction error: {e}")
        return []

def extract_scenes_with_ffmpeg(video_path, output_dir, sensitivity=0.15):
    """FFmpegベースのシーン検出"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # シーン検出でタイムスタンプを取得
        scene_cmd = [
            'ffmpeg', '-i', video_path,
            '-vf', f'select=gt(scene\\,{sensitivity}),showinfo',
            '-vsync', 'vfr',
            '-f', 'null', '-'
        ]
        
        result = subprocess.run(scene_cmd, capture_output=True, text=True, timeout=120)
        
        # タイムスタンプを抽出
        timestamps = []
        lines = result.stderr.split('\n')
        
        for line in lines:
            if '[Parsed_showinfo_1' in line and 'pts_time:' in line:
                try:
                    pts_start = line.find('pts_time:') + 9
                    pts_end = line.find(' ', pts_start)
                    if pts_end == -1:
                        pts_end = len(line)
                    
                    timestamp_str = line[pts_start:pts_end].strip()
                    timestamp = float(timestamp_str)
                    timestamps.append(timestamp)
                except ValueError:
                    continue
        
        if 0.0 not in timestamps:
            timestamps.insert(0, 0.0)
        
        timestamps = sorted(list(set(timestamps)))
        
        if len(timestamps) <= 1:
            # フォールバック：定間隔
            return extract_frames_simple(video_path, output_dir, 5)
        
        # フレーム抽出
        frames = []
        for i, timestamp in enumerate(timestamps[:20]):  # 最大20フレーム
            output_filename = f'scene_{i+1:03d}.jpg'
            output_path = os.path.join(output_dir, output_filename)
            
            cmd = [
                'ffmpeg', '-ss', str(timestamp), '-i', video_path,
                '-frames:v', '1', '-q:v', '2', '-y',
                output_path
            ]
            
            frame_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if frame_result.returncode == 0 and os.path.exists(output_path):
                frames.append(output_filename)
        
        return frames
        
    except Exception as e:
        print(f"Scene detection error: {e}")
        return []

@app.route('/static/scenes/<path:filename>')
def serve_scene_file(filename):
    """抽出されたシーン画像を配信"""
    return send_from_directory(SCENES_FOLDER, filename)

@app.route('/videos/<path:filename>')
def serve_video(filename):
    """アップロードされた動画ファイルを配信"""
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)