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
        
        # まずFFmpegを試行
        frames = extract_frames_simple(filepath, scene_dir)
        
        if frames:
            return jsonify({
                'message': 'Video processed successfully',
                'filename': file.filename,
                'frames': len(frames),
                'preview_url': f'/scenes/{filename_no_ext}/{frames[0]}' if frames else None
            })
        
        # FFmpegが失敗した場合、代替処理を試行
        frames = create_placeholder_frames(filepath, scene_dir, file.filename)
        
        if frames:
            return jsonify({
                'message': 'Video uploaded successfully (using placeholder processing)',
                'filename': file.filename,
                'frames': len(frames),
                'preview_url': f'/scenes/{filename_no_ext}/{frames[0]}' if frames else None,
                'note': 'Using placeholder frame generation. Full video processing coming soon!'
            })
        else:
            return jsonify({
                'message': 'Video uploaded but processing failed',
                'filename': file.filename,
                'note': 'Video processing is not available on this platform'
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