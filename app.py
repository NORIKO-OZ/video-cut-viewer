import os
import sys
import uuid
import glob
from flask import Flask, render_template, request, redirect
from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector
import cv2
from PIL import Image
from scenedetect.scene_manager import save_images

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

def capture_screenshots_by_interval_pillow(video_path, output_dir, interval_sec=5):
    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    timestamps = []

    if not cap.isOpened():
        print(f"Failed to open video: {video_path}")
        return timestamps

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = frame_count / fps
    print(f"Video opened: duration {duration_sec}s, fps {fps}")

    times = [i for i in range(0, int(duration_sec), interval_sec)]

    for idx, t in enumerate(times):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            filename = os.path.join(output_dir, f"screenshot_{idx+1:03d}.jpg")
            try:
                img.save(filename)
                print(f"Saved screenshot (Pillow): {filename}")
                timestamps.append(t)  # ここで秒数を記録
            except Exception as e:
                print(f"Failed to save screenshot (Pillow): {filename}, error: {e}")
        else:
            print(f"Failed to capture frame at {t} seconds")

    cap.release()
    return timestamps

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        mode = request.form.get('mode', 'scene')
        interval = request.form.get('interval')
        print(f"Received mode: '{mode}', interval: '{interval}'")

        file = request.files.get('video')
        if not file:
            return redirect(request.url)

        original_name = file.filename
        filename = f"{uuid.uuid4().hex}{os.path.splitext(original_name)[1]}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        print(f"base_dir: {base_dir}")
        print(f"UPLOAD_FOLDER: {UPLOAD_FOLDER}")
        print(f"Saved video file path: {filepath}")

        filename_no_ext = os.path.splitext(filename)[0]
        scene_dir = os.path.join(SCENES_FOLDER, filename_no_ext)
        os.makedirs(scene_dir, exist_ok=True)

        if mode == 'time':
            print(">>> Time mode selected")
            interval_sec = int(interval or 5)
            timestamps = capture_screenshots_by_interval_pillow(filepath, scene_dir, interval_sec)
            saved_files = sorted(os.listdir(scene_dir))
            scene_list = []

            def seconds_to_timecode(seconds):
                h = seconds // 3600
                m = (seconds % 3600) // 60
                s = seconds % 60
                return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

            scenes = [{
                'image': f"{filename_no_ext}/{fname}",
                'start': seconds_to_timecode(ts)
            } for fname, ts in zip(saved_files, timestamps)]

        else:
            print(">>> Scene detection mode selected")
            video_manager = VideoManager([filepath])
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector())
            video_manager.start()
            scene_manager.detect_scenes(frame_source=video_manager)
            scene_list = scene_manager.get_scene_list()

            print(f"検出されたシーン数: {len(scene_list)}")
            for i, (start, end) in enumerate(scene_list):
                print(f"Scene {i+1}: Start = {start.get_timecode()}, End = {end.get_timecode()}")

            print(f"保存先ディレクトリ: {scene_dir}")

            save_images(scene_list, video_manager, num_images=1, output_dir=scene_dir)
            print("画像保存完了")

            saved_files = sorted(glob.glob(os.path.join(scene_dir, '*.jpg')))
            for i, path in enumerate(saved_files, start=1):
                new_name = f"scene_{i:03d}.jpg"
                new_path = os.path.join(scene_dir, new_name)
                os.rename(path, new_path)

            saved_files = sorted(os.listdir(scene_dir))
            video_manager.release()

            scenes = [{
                'image': f"{filename_no_ext}/{fname}",
                'start': start.get_timecode()
            } for fname, (start, _) in zip(saved_files, scene_list)]

        return render_template('index.html', video=filename, scenes=scenes, selected_mode=mode, interval=interval)

    return render_template('index.html', video=None, scenes=None, selected_mode='scene')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
