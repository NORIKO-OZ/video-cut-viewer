import os
import sys
import uuid
import subprocess
import tempfile
import shutil
from flask import Flask, render_template, request, jsonify, send_from_directory
from PIL import Image
try:
    import ffmpeg
    FFMPEG_AVAILABLE = True
except ImportError:
    FFMPEG_AVAILABLE = False

# PySceneDetectは重い依存関係のため無効化
SCENEDETECT_AVAILABLE = False

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
        mode = request.form.get('mode', 'interval')  # 'interval' or 'scene'
        interval = int(request.form.get('interval', 5))
        
        print(f"=== FORM DATA DEBUG ===")
        print(f"All form data: {dict(request.form)}")
        print(f"Processing mode: '{mode}' (type: {type(mode)})")
        print(f"Interval: {interval}")
        print(f"SceneDetect available: {SCENEDETECT_AVAILABLE}")
        print(f"=== END FORM DATA DEBUG ===")
        
        # フレーム抽出を試行
        filename_no_ext = os.path.splitext(filename)[0]
        scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
        
        # FFmpeg可用性チェック
        ffmpeg_status = check_ffmpeg_availability()
        
        # 処理モードに応じて実行
        if mode == 'scene':
            print("Using FFmpeg-based scene detection mode")
            frames = extract_scenes_with_ffmpeg(filepath, scene_dir)
            processing_method = 'intelligent scene extraction (FFmpeg-based)'
        else:
            print(f"Using interval mode with {interval}s interval")
            frames = extract_frames_simple(filepath, scene_dir, interval)
            processing_method = f'interval extraction ({interval}s)'
        
        if frames:
            return jsonify({
                'message': f'Video processed successfully using {processing_method}',
                'filename': file.filename,
                'frames': len(frames),
                'preview_url': f'/scenes/{filename_no_ext}/{frames[0]}' if frames else None,
                'processing_method': processing_method,
                'requested_mode': mode,
                'debug_info': format_debug_info(ffmpeg_status)
            })
        
        # FFmpegが失敗した場合、代替処理を試行
        frames = create_placeholder_frames(filepath, scene_dir, file.filename)
        
        if frames:
            return jsonify({
                'message': 'Video uploaded successfully (using placeholder processing)',
                'filename': file.filename,
                'frames': len(frames),
                'preview_url': f'/scenes/{filename_no_ext}/{frames[0]}' if frames else None,
                'note': 'Using placeholder frame generation. Real video processing failed.',
                'debug_info': format_debug_info(ffmpeg_status)
            })
        else:
            return jsonify({
                'message': 'Video uploaded but processing failed',
                'filename': file.filename,
                'note': 'Video processing is not available on this platform',
                'debug_info': format_debug_info(ffmpeg_status)
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def check_ffmpeg_availability():
    """FFmpegの利用可能性をチェック"""
    status = {}
    
    # ffmpeg-pythonライブラリの確認
    status['ffmpeg_python_lib'] = FFMPEG_AVAILABLE
    
    # PySceneDetectの確認
    status['scenedetect_available'] = SCENEDETECT_AVAILABLE
    
    # より多くのパスでFFmpegを検索
    ffmpeg_paths = [
        'ffmpeg', 
        '/usr/bin/ffmpeg', 
        '/usr/local/bin/ffmpeg', 
        '/opt/ffmpeg/bin/ffmpeg',
        '/app/.heroku/usr/bin/ffmpeg',
        '/app/.apt/usr/bin/ffmpeg',
        '/usr/local/stow/ffmpeg/bin/ffmpeg'
    ]
    
    for ffmpeg_path in ffmpeg_paths:
        try:
            result = subprocess.run([ffmpeg_path, '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                status['ffmpeg_binary'] = 'Available'
                status['ffmpeg_path'] = ffmpeg_path
                # バージョン情報の最初の行を取得
                version_line = result.stdout.split('\n')[0]
                status['ffmpeg_version'] = version_line
                
                # ffprobeもチェック
                try:
                    probe_result = subprocess.run(['ffprobe', '-version'], 
                                                capture_output=True, text=True, timeout=5)
                    status['ffprobe_available'] = probe_result.returncode == 0
                except:
                    status['ffprobe_available'] = False
                
                return status
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        except Exception as e:
            status['last_error'] = str(e)
            continue
    
    # すべてのパスで見つからなかった場合、whichコマンドで検索
    try:
        which_result = subprocess.run(['which', 'ffmpeg'], 
                                    capture_output=True, text=True, timeout=5)
        if which_result.returncode == 0:
            ffmpeg_path = which_result.stdout.strip()
            if ffmpeg_path:
                status['ffmpeg_binary'] = 'Available'
                status['ffmpeg_path'] = f'{ffmpeg_path} (found via which)'
                # バージョンを取得
                try:
                    version_result = subprocess.run([ffmpeg_path, '-version'], 
                                                  capture_output=True, text=True, timeout=5)
                    if version_result.returncode == 0:
                        version_line = version_result.stdout.split('\n')[0]
                        status['ffmpeg_version'] = version_line
                except:
                    pass
                return status
    except:
        pass
    
    # それでも見つからない場合
    status['ffmpeg_binary'] = 'Not found'
    status['searched_paths'] = ', '.join(ffmpeg_paths)
    
    return status

def format_debug_info(status):
    """デバッグ情報を読みやすい形式に整形"""
    info_lines = []
    info_lines.append(f"• ffmpeg-python library: {'✅ Available' if status.get('ffmpeg_python_lib') else '❌ Not available'}")
    info_lines.append("• Scene detection: ✅ FFmpeg-based (lightweight)")
    
    binary_status = status.get('ffmpeg_binary', 'Unknown')
    if binary_status == 'Available':
        info_lines.append("• FFmpeg binary: ✅ Available")
        if 'ffmpeg_path' in status:
            info_lines.append(f"• Path: {status['ffmpeg_path']}")
        if 'ffmpeg_version' in status:
            version = status['ffmpeg_version'][:60] + "..." if len(status['ffmpeg_version']) > 60 else status['ffmpeg_version']
            info_lines.append(f"• Version: {version}")
    else:
        info_lines.append(f"• FFmpeg binary: ❌ {binary_status}")
        if 'searched_paths' in status:
            info_lines.append(f"• Searched paths: {status['searched_paths']}")
        if 'last_error' in status:
            info_lines.append(f"• Last error: {status['last_error']}")
    
    return "<br>".join(info_lines)

def extract_frames_simple(video_path, output_dir, interval_sec=5):
    """動画からフレームを抽出（ffmpeg-pythonまたはsubprocessを使用）"""
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Starting frame extraction from: {video_path}")
    print(f"Output directory: {output_dir}")
    print(f"FFmpeg Python available: {FFMPEG_AVAILABLE}")
    
    # まずffmpeg-pythonを試行
    if FFMPEG_AVAILABLE:
        try:
            print("Trying ffmpeg-python approach...")
            result = extract_frames_with_ffmpeg_python(video_path, output_dir, interval_sec)
            if result:
                return result
        except Exception as e:
            print(f"ffmpeg-python failed: {e}")
            import traceback
            traceback.print_exc()
    
    # フォールバック: 直接subprocessでffmpegを呼び出し
    try:
        print("Trying subprocess approach...")
        result = extract_frames_with_subprocess(video_path, output_dir, interval_sec)
        if result:
            return result
    except Exception as e:
        print(f"subprocess ffmpeg failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("All FFmpeg approaches failed, falling back to placeholder")
    return []

def extract_frames_with_ffmpeg_python(video_path, output_dir, interval_sec=5):
    """ffmpeg-pythonを使用したフレーム抽出"""
    try:
        # 動画情報を取得
        probe = ffmpeg.probe(video_path)
        duration = float(probe['streams'][0]['duration'])
        
        # フレーム抽出
        output_pattern = os.path.join(output_dir, 'frame_%03d.jpg')
        (
            ffmpeg
            .input(video_path)
            .filter('fps', fps=f'1/{interval_sec}')
            .output(output_pattern, vcodec='mjpeg', qscale=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True, timeout=120)
        )
        
        # 生成されたファイルを取得
        files = sorted([f for f in os.listdir(output_dir) if f.endswith('.jpg')])
        print(f"Successfully extracted {len(files)} frames using ffmpeg-python")
        return files
        
    except Exception as e:
        print(f"ffmpeg-python extraction error: {e}")
        raise

def extract_frames_with_subprocess(video_path, output_dir, interval_sec=5):
    """subprocessを使用したFFmpeg呼び出し"""
    try:
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
            print(f"Successfully extracted {len(files)} frames using subprocess")
            return files
        else:
            print(f"FFmpeg subprocess error: {result.stderr}")
            return []
        
    except subprocess.TimeoutExpired:
        print("FFmpeg timeout")
        return []
    except FileNotFoundError:
        print("FFmpeg binary not found")
        return []

def extract_scenes_with_detection(video_path, output_dir):
    """PySceneDetectを使用したシーン検出ベースのフレーム抽出"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        print(f"Starting scene detection for: {video_path}")
        
        # VideoManagerでビデオを開く
        video_manager = VideoManager([video_path])
        scene_manager = SceneManager()
        
        # ContentDetectorを追加（閾値30.0で設定）
        scene_manager.add_detector(ContentDetector(threshold=30.0))
        
        # シーン検出を実行
        video_manager.set_downscale_factor()
        video_manager.start()
        scene_manager.detect_scenes(frame_source=video_manager)
        scene_list = scene_manager.get_scene_list()
        
        print(f"Detected {len(scene_list)} scenes")
        
        if not scene_list:
            print("No scenes detected, falling back to interval extraction")
            return []
        
        # 各シーンの開始フレームを抽出
        frames = []
        video_fps = video_manager.get_framerate()
        
        for i, scene in enumerate(scene_list):
            try:
                start_time = scene[0].get_seconds()
                
                # FFmpegでそのタイミングのフレームを抽出
                output_filename = f'scene_{i+1:03d}.jpg'
                output_path = os.path.join(output_dir, output_filename)
                
                # FFmpegコマンドで特定の時間のフレームを抽出
                cmd = [
                    'ffmpeg', '-ss', str(start_time), '-i', video_path,
                    '-frames:v', '1', '-q:v', '2', '-y',
                    output_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(output_path):
                    frames.append(output_filename)
                    print(f"Extracted scene {i+1} at {start_time:.2f}s")
                else:
                    print(f"Failed to extract scene {i+1}: {result.stderr}")
                    
            except Exception as e:
                print(f"Error extracting scene {i+1}: {e}")
                continue
        
        video_manager.release()
        print(f"Successfully extracted {len(frames)} scene frames")
        return frames
        
    except Exception as e:
        print(f"Scene detection failed: {e}")
        import traceback
        traceback.print_exc()
        return []

def extract_scenes_with_ffmpeg(video_path, output_dir):
    """FFmpegを使用したシンプルなシーン抽出"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        print(f"Starting FFmpeg-based scene detection for: {video_path}")
        print(f"Output directory: {output_dir}")
        print(f"Video file exists: {os.path.exists(video_path)}")
        if os.path.exists(video_path):
            print(f"Video file size: {os.path.getsize(video_path)} bytes")
        
        # 動画の基本情報を取得
        probe_cmd = ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', video_path]
        print(f"Running probe command: {' '.join(probe_cmd)}")
        duration_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        
        if duration_result.returncode != 0:
            print(f"Failed to get video duration - return code: {duration_result.returncode}")
            print(f"ffprobe stderr: {duration_result.stderr}")
            return []
        
        try:
            duration = float(duration_result.stdout.strip())
        except ValueError:
            print(f"Invalid duration format: '{duration_result.stdout.strip()}'")
            return []
        
        print(f"Video duration: {duration:.2f} seconds")
        
        # シンプルなアプローチ: 動画の長さに基づいて時間を決定
        # 短い動画: より頻繁、長い動画: より間隔を空ける
        if duration <= 30:
            interval = 3  # 30秒以下: 3秒間隔
        elif duration <= 120:
            interval = 8  # 2分以下: 8秒間隔
        elif duration <= 300:
            interval = 15  # 5分以下: 15秒間隔
        else:
            interval = 20  # 5分以上: 20秒間隔
        
        # タイムスタンプを生成
        timestamps = []
        current_time = 0
        while current_time < duration and len(timestamps) < 20:  # 最大20フレーム
            timestamps.append(current_time)
            current_time += interval
        
        # 最後のフレームも追加（動画の最後付近）
        if duration > interval and (duration - timestamps[-1]) > interval / 2:
            timestamps.append(duration - 2)  # 最後の2秒前
        
        print(f"Generated {len(timestamps)} timestamps at {interval}s intervals: {timestamps}")
        
        # 各タイムスタンプでフレームを抽出
        frames = []
        for i, timestamp in enumerate(timestamps):
            try:
                output_filename = f'scene_{i+1:03d}.jpg'
                output_path = os.path.join(output_dir, output_filename)
                
                cmd = [
                    'ffmpeg', '-ss', str(timestamp), '-i', video_path,
                    '-frames:v', '1', '-q:v', '2', '-y',
                    output_path
                ]
                
                print(f"Extracting frame {i+1} at {timestamp:.2f}s")
                frame_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if frame_result.returncode == 0 and os.path.exists(output_path):
                    frames.append(output_filename)
                    print(f"Successfully extracted scene {i+1} at {timestamp:.2f}s")
                else:
                    print(f"Failed to extract scene {i+1}: {frame_result.stderr}")
                    
            except Exception as e:
                print(f"Error extracting scene {i+1}: {e}")
                continue
        
        print(f"Successfully extracted {len(frames)} scene frames using intelligent intervals")
        return frames
        
    except Exception as e:
        print(f"FFmpeg scene extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return []

def create_placeholder_frames(video_path, output_dir, original_filename):
    """プレースホルダーフレームを生成"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # 動画ファイルの情報を取得
        file_size = os.path.getsize(video_path)
        file_size_mb = file_size / (1024 * 1024)
        
        # より実用的なフレーム数計算
        # ファイルサイズから大まかな動画時間を推定（粗い近似）
        # 一般的に 1分の動画 ≈ 10-50MB（品質による）
        estimated_duration_minutes = max(1, file_size_mb / 15)  # 15MB/分と仮定
        
        # 5秒間隔でフレーム抽出と仮定
        frames_per_minute = 12  # 60秒 / 5秒間隔
        estimated_frames = int(estimated_duration_minutes * frames_per_minute)
        
        # 実用的な範囲に制限（3〜20枚）
        num_frames = min(20, max(3, estimated_frames))
        frames = []
        
        for i in range(num_frames):
            # 600x400のプレースホルダー画像を作成
            img = Image.new('RGB', (600, 400), color=(70, 130, 180))
            
            # 簡単なテキストを描画風に見せるために色付きの矩形を追加
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            
            # 背景グラデーション風
            for y in range(0, 400, 20):
                color_intensity = int(70 + (y / 400) * 60)
                draw.rectangle([0, y, 600, y+20], fill=(color_intensity, color_intensity+20, 180))
            
            # フレーム情報
            frame_time = i * 5  # 5秒間隔を仮定
            minutes = frame_time // 60
            seconds = frame_time % 60
            
            # テキスト領域（白い背景）
            draw.rectangle([50, 120, 550, 280], fill=(255, 255, 255, 220))
            draw.rectangle([52, 122, 548, 278], outline=(100, 100, 100), width=2)
            
            # ファイル名を短縮
            display_name = original_filename[:25] + "..." if len(original_filename) > 25 else original_filename
            
            # より詳細な情報表示用の矩形
            # フレーム番号
            draw.rectangle([70, 140, 300, 150], fill=(50, 100, 150))
            # 時間情報
            draw.rectangle([70, 160, 250, 170], fill=(100, 100, 100))
            # ファイル名
            draw.rectangle([70, 180, 400, 190], fill=(150, 150, 150))
            # ファイルサイズ情報
            draw.rectangle([70, 200, 320, 210], fill=(120, 120, 120))
            # 推定時間情報
            draw.rectangle([70, 220, 380, 230], fill=(80, 80, 80))
            # フレーム総数
            draw.rectangle([70, 240, 280, 250], fill=(60, 60, 60))
            
            filename = f'frame_{i+1:03d}.jpg'
            filepath = os.path.join(output_dir, filename)
            img.save(filepath, 'JPEG', quality=85)
            frames.append(filename)
        
        return frames
        
    except Exception as e:
        print(f"Error creating placeholder frames: {e}")
        return []

@app.route('/scenes/<path:filename>')
def serve_scene(filename):
    return send_from_directory(SCENES_FOLDER, filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)