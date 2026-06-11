from flask import Flask, request, jsonify
import cv2
import requests
import numpy as np
import easyocr
import re
import threading
import time
import mysql.connector

# =====================================
# KONFIGURASI
# =====================================

URL_KAMERA = "http://172.20.10.4/capture"

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "db_parkir"
}

# INIT

app = Flask(__name__)

reader = easyocr.Reader(['en'], gpu=False)

LAST_DETECTED_PLATE = "UNKNOWN"

# =====================================
# DATABASE
# =====================================

def koneksi_db():
    return mysql.connector.connect(**DB_CONFIG)

# =====================================
# NORMALISASI PLAT
# =====================================

def normalisasi_plat(text):

    text = text.upper()

    text = re.sub(r'[^A-Z0-9]', '', text)

    pola = re.search(
        r'([A-Z]{1,2})([0-9]{1,4})([A-Z]{1,3})',
        text
    )

    if pola:

        depan = pola.group(1)
        angka = pola.group(2)
        belakang = pola.group(3)

        return f"{depan} {angka} {belakang}"

    return "UNKNOWN"

# =====================================
# AMBIL GAMBAR ESP32CAM
# =====================================

def ambil_gambar():

    try:

        response = requests.get(URL_KAMERA, timeout=5)

        if response.status_code == 200:

            img_arr = np.frombuffer(
                response.content,
                np.uint8
            )

            img = cv2.imdecode(
                img_arr,
                cv2.IMREAD_COLOR
            )

            return img

        return None

    except Exception as e:

        print("ERROR CAMERA :", e)

        return None

# =====================================
# OCR LOOP REALTIME
# =====================================

def ocr_loop():

    global LAST_DETECTED_PLATE

    while True:

        frame = ambil_gambar()

        if frame is not None:

            # ==========================
            # RESIZE
            # ==========================

            frame = cv2.resize(
                frame,
                None,
                fx=2,
                fy=2
            )

            # ==========================
            # CROP AREA TENGAH
            # ==========================

            h, w, _ = frame.shape

            crop = frame[
                int(h * 0.35):int(h * 0.85),
                int(w * 0.10):int(w * 0.90)
            ]

            # ==========================
            # PREPROCESS OCR
            # ==========================

            gray = cv2.cvtColor(
                crop,
                cv2.COLOR_BGR2GRAY
            )

            blur = cv2.GaussianBlur(
                gray,
                (5,5),
                0
            )

            thresh = cv2.threshold(
                blur,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )[1]

            # ==========================
            # OCR
            # ==========================

            hasil = reader.readtext(
                thresh,
                detail=0
            )

            print("OCR RAW :", hasil)

            if hasil:

                gabung = " ".join(hasil)

                plat = normalisasi_plat(gabung)

                if plat != "UNKNOWN":

                    LAST_DETECTED_PLATE = plat

                    print("PLAT TERDETEKSI :",
                          LAST_DETECTED_PLATE)

            # ==========================
            # PREVIEW
            # ==========================

            cv2.imshow("ESP32CAM", crop)

            cv2.imshow("OCR", thresh)

            cv2.waitKey(1)

        time.sleep(1)

# =====================================
# UPDATE SLOT TERISI
# =====================================

def update_slot_terisi(slot):

    global LAST_DETECTED_PLATE

    conn = koneksi_db()

    cur = conn.cursor()

    sql = """
    UPDATE slot_parkir
    SET
        status='terisi',
        plat_nomor=%s,
        waktu_masuk=NOW()
    WHERE nomor_slot=%s
    """

    cur.execute(sql, (
        LAST_DETECTED_PLATE,
        slot
    ))

    conn.commit()

    cur.close()
    conn.close()

    print("================================")
    print("SLOT :", slot)
    print("PLAT :", LAST_DETECTED_PLATE)
    print("================================")

# =====================================
# UPDATE SLOT KOSONG
# =====================================

def update_slot_kosong(slot):

    conn = koneksi_db()

    cur = conn.cursor()

    sql = """
    UPDATE slot_parkir
    SET
        status='kosong',
        waktu_keluar=NOW()
    WHERE nomor_slot=%s
    """

    cur.execute(sql, (slot,))

    conn.commit()

    cur.close()
    conn.close()

# =====================================
# ENDPOINT SLOT
# =====================================

@app.route('/update_slot', methods=['POST'])
def update_slot():

    data = request.json

    slot = data['slot']

    status = data['status']

    print("STATUS SLOT :", slot, status)

    if status.lower() == "terisi":

        update_slot_terisi(slot)

    elif status.lower() == "kosong":

        update_slot_kosong(slot)

    return jsonify({
        "success": True,
        "last_plate": LAST_DETECTED_PLATE
    })

# =====================================
# ENDPOINT LAST PLATE
# =====================================

@app.route('/last_plate')
def last_plate():

    return jsonify({
        "plate": LAST_DETECTED_PLATE
    })

# =====================================
# MAIN
# =====================================

if __name__ == '__main__':

    # JALANKAN OCR LOOP
    thread_ocr = threading.Thread(
        target=ocr_loop
    )

    thread_ocr.daemon = True

    thread_ocr.start()

    print("================================")
    print(" SMART PARKING ACTIVE ")
    print(" OCR REALTIME ACTIVE ")
    print("================================")

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False
    )