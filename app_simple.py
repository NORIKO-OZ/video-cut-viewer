import os
import sys
import uuid
import subprocess
import tempfile
import shutil
from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from io import BytesIO

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

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            if 'video' not in request.files:
                return render_template('index.html', error='動画ファイルを選択してください')
            
            file = request.files['video']
            if file.filename == '':
                return render_template('index.html', error='動画ファイルを選択してください')
            
            # ファイル保存
            original_filename = file.filename
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # 処理モードを取得
            mode = request.form.get('mode', 'interval')
            interval = int(request.form.get('interval', 5))
            
            print(f"Processing mode: {mode}, interval: {interval}s")
            
            # フレーム抽出
            filename_no_ext = os.path.splitext(filename)[0]
            scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
            
            if mode == 'scene':
                frame_data = extract_scenes_with_ffmpeg(filepath, scene_dir)
            else:
                frame_data = extract_frames_simple(filepath, scene_dir, interval)
            
            # シーンデータを構築
            scenes = []
            if frame_data:
                for i, frame_file in enumerate(frame_data):
                    # 簡単な時間計算（実際の時間ではなく推定）
                    timestamp_seconds = i * (interval if mode == 'interval' else 10)
                    hours = timestamp_seconds // 3600
                    minutes = (timestamp_seconds % 3600) // 60
                    secs = timestamp_seconds % 60
                    time_str = f"{hours:02d}:{minutes:02d}:{secs:02d}.000"
                    
                    scenes.append({
                        'image': f"{filename_no_ext}/{frame_file}",
                        'start': time_str
                    })
            
            return render_template('index.html', 
                                 video=filename, 
                                 original_filename=original_filename,
                                 scenes=scenes, 
                                 selected_mode=mode, 
                                 interval=interval)
            
        except Exception as e:
            print(f"Error processing video: {e}")
            return render_template('index.html', error=f'動画処理中にエラーが発生しました: {str(e)}')
    
    return render_template('index.html')

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

@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    """アップロードされた動画ファイルを配信"""
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/export_pdf')
def export_pdf():
    """PDF形式で解析結果をエクスポート"""
    try:
        # クエリパラメータから情報を取得
        video_filename = request.args.get('video')
        original_filename = request.args.get('original_filename', video_filename)
        mode = request.args.get('mode', 'interval')
        interval = request.args.get('interval', '5')
        
        if not video_filename:
            return "動画ファイル名が指定されていません", 400
        
        # ファイル名から拡張子を除いた部分を取得
        filename_no_ext = os.path.splitext(video_filename)[0]
        scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
        
        if not os.path.exists(scene_dir):
            return "解析結果が見つかりません", 404
        
        # 画像ファイルを取得
        image_files = sorted([f for f in os.listdir(scene_dir) if f.endswith('.jpg')])
        
        if not image_files:
            return "画像ファイルが見つかりません", 404
        
        # PDF生成
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                              rightMargin=inch*0.5, leftMargin=inch*0.5,
                              topMargin=inch*0.5, bottomMargin=inch*0.5)
        
        # スタイル設定（日本語対応）
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1,  # 中央揃え
            textColor=colors.darkgreen,
            fontName='Helvetica-Bold'
        )
        
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=20,
            alignment=1,  # 中央揃え
            textColor=colors.darkgrey,
            fontName='Helvetica'
        )
        
        # コンテンツを構築
        story = []
        
        # タイトル
        story.append(Paragraph("Video Analysis Report", title_style))
        
        # 基本情報
        mode_text = "Scene Detection" if mode == 'scene' else f"Interval Extraction ({interval}s)"
        story.append(Paragraph(f"Analysis Method: {mode_text}", subtitle_style))
        story.append(Paragraph(f"Video File: {original_filename}", subtitle_style))
        story.append(Paragraph(f"Extracted Frames: {len(image_files)} frames", subtitle_style))
        story.append(Spacer(1, 20))
        
        # 各シーンの情報
        for i, image_file in enumerate(image_files):
            try:
                # 時間計算（シンプルな推定）
                timestamp_seconds = i * (int(interval) if mode == 'interval' else 10)
                hours = timestamp_seconds // 3600
                minutes = (timestamp_seconds % 3600) // 60
                secs = timestamp_seconds % 60
                time_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
                
                # 画像パス
                image_path = os.path.join(scene_dir, image_file)
                
                if os.path.exists(image_path):
                    # 元画像のサイズを取得して比率を保持
                    with Image.open(image_path) as pil_img:
                        width, height = pil_img.size
                        aspect_ratio = width / height
                    
                    # PDF用画像サイズを比率を保持して設定
                    max_width = 4.5 * inch
                    max_height = 3 * inch
                    
                    if aspect_ratio > max_width / max_height:
                        # 横長の場合
                        img_width = max_width
                        img_height = max_width / aspect_ratio
                    else:
                        # 縦長の場合
                        img_height = max_height
                        img_width = max_height * aspect_ratio
                    
                    # 画像オブジェクト作成
                    img = RLImage(image_path)
                    img.drawWidth = img_width
                    img.drawHeight = img_height
                    
                    # シーン情報テーブル
                    scene_data = [
                        [f"Scene {i+1}", f"Time: {time_str}"],
                        [img, ""]
                    ]
                    
                    scene_table = Table(scene_data, colWidths=[max_width, 1.5*inch])
                    scene_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (1, 0), 12),
                        ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
                        ('BACKGROUND', (0, 0), (1, 0), colors.lightgreen),
                    ]))
                    
                    story.append(scene_table)
                    story.append(Spacer(1, 15))
                    
            except Exception as e:
                print(f"Error processing image {image_file}: {e}")
                continue
        
        # PDF生成
        doc.build(story)
        buffer.seek(0)
        
        # 元ファイル名からPDFファイル名を作成
        pdf_filename = os.path.splitext(original_filename)[0] + "_analysis.pdf"
        
        # レスポンス作成
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
        
        return response
        
    except Exception as e:
        print(f"PDF export error: {e}")
        return f"PDF作成中にエラーが発生しました: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)