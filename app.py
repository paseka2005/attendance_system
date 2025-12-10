import os
import sqlite3
import uuid
import qrcode
import io
import csv
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

# ================== БАЗА ДАННЫХ ==================

def init_db():
    """Инициализация базы данных"""
    # На Render используем /tmp папку, локально - текущую папку
    if 'RENDER' in os.environ:
        db_path = '/tmp/attendance.db'
        print("🔧 Используем БД на Render:", db_path)
    else:
        db_path = 'attendance.db'
        print("🔧 Используем локальную БД:", db_path)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Таблица студентов (3 человека)
    c.execute('''CREATE TABLE IF NOT EXISTS students
                 (id INTEGER PRIMARY KEY, 
                  name TEXT NOT NULL, 
                  group_name TEXT NOT NULL)''')
    
    # Таблица занятий
    c.execute('''CREATE TABLE IF NOT EXISTS classes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  subject TEXT NOT NULL,
                  date_time TEXT NOT NULL,
                  qr_token TEXT UNIQUE)''')
    
    # Таблица посещаемости
    c.execute('''CREATE TABLE IF NOT EXISTS attendance
                 (student_id INTEGER,
                  class_id INTEGER,
                  status TEXT DEFAULT 'absent',
                  scan_time TEXT,
                  PRIMARY KEY(student_id, class_id))''')
    
    # Добавляем 3-х тестовых студентов
    c.execute("SELECT COUNT(*) FROM students")
    if c.fetchone()[0] == 0:
        students = [
            (1, 'Иван Петров', 'Группа 101'),
            (2, 'Мария Сидорова', 'Группа 101'),
            (3, 'Алексей Иванов', 'Группа 102')
        ]
        c.executemany("INSERT INTO students VALUES (?, ?, ?)", students)
        print("✅ Добавлены 3 тестовых студента")
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")
    return db_path

def get_db():
    """Подключение к базе данных"""
    if 'RENDER' in os.environ:
        db_path = '/tmp/attendance.db'
    else:
        db_path = 'attendance.db'
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
    return conn

# Инициализируем БД при старте
DB_PATH = init_db()

# ================== ГЛАВНЫЕ СТРАНИЦЫ ==================

@app.route('/')
def index():
    """Главная страница преподавателя"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Получаем все занятия
        c.execute("SELECT * FROM classes ORDER BY date_time DESC")
        classes = c.fetchall()
        
        # Получаем всех студентов
        c.execute("SELECT * FROM students")
        students = c.fetchall()
        
        # Получаем посещаемость для последнего занятия (если есть)
        attendance = []
        selected_class_id = None
        
        if classes:
            selected_class_id = classes[0]['id']
            c.execute('''SELECT s.id, s.name, s.group_name, 
                                COALESCE(a.status, 'absent') as status
                         FROM students s
                         LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = ?
                         ORDER BY s.group_name, s.name''', (selected_class_id,))
            attendance = c.fetchall()
        
        conn.close()
        
        return render_template('index.html',
                             classes=classes,
                             students=students,
                             attendance=attendance,
                             selected_class=selected_class_id)
    except Exception as e:
        return f"Ошибка: {str(e)}", 500

@app.route('/scan')
def scan():
    """Страница сканирования для студентов"""
    # Можно добавить логику для определения мобильного устройства
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(word in user_agent for word in ['mobile', 'android', 'iphone'])
    return render_template('scan.html', is_mobile=is_mobile)

# ================== API ДЛЯ ЗАНЯТИЙ ==================

@app.route('/api/create_class', methods=['POST'])
def create_class():
    """Создание нового занятия"""
    try:
        subject = request.form.get('subject', '').strip()
        date_time = request.form.get('date_time', '').strip()
        
        if not subject or not date_time:
            return jsonify({'success': False, 'error': 'Заполните все поля'})
        
        conn = get_db()
        c = conn.cursor()
        
        # Генерируем уникальный токен для QR-кода
        qr_token = str(uuid.uuid4())
        
        c.execute(
            "INSERT INTO classes (subject, date_time, qr_token) VALUES (?, ?, ?)",
            (subject, date_time, qr_token)
        )
        
        class_id = c.lastrowid
        conn.commit()
        conn.close()
        
        print(f"✅ Создано занятие: {subject} (ID: {class_id})")
        
        return jsonify({
            'success': True,
            'class_id': class_id,
            'message': 'Занятие успешно создано'
        })
        
    except Exception as e:
        print(f"❌ Ошибка при создании занятия: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/delete_class/<int:class_id>', methods=['DELETE'])
def delete_class(class_id):
    """Удаление занятия"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Сначала удаляем связанную посещаемость
        c.execute("DELETE FROM attendance WHERE class_id = ?", (class_id,))
        
        # Затем удаляем само занятие
        c.execute("DELETE FROM classes WHERE id = ?", (class_id,))
        
        conn.commit()
        conn.close()
        
        print(f"🗑️ Удалено занятие ID: {class_id}")
        
        return jsonify({
            'success': True,
            'message': 'Занятие успешно удалено'
        })
        
    except Exception as e:
        print(f"❌ Ошибка удаления занятия: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get_classes')
def get_classes():
    """Получение списка всех занятий"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM classes ORDER BY date_time DESC")
        classes = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(classes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ================== ГЕНЕРАЦИЯ QR-КОДОВ ==================

@app.route('/api/generate_qr/<int:class_id>')
def generate_qr(class_id):
    """Генерация QR-кода для занятия"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Получаем занятие
        c.execute("SELECT * FROM classes WHERE id = ?", (class_id,))
        class_data = c.fetchone()
        
        if not class_data:
            return jsonify({'error': 'Занятие не найдено'}), 404
        
        # Получаем токен занятия
        qr_token = class_data['qr_token']
        
        # Создаем правильную ссылку для отметки
        # На Render используем абсолютный URL
        if 'RENDER' in os.environ:
            # Получаем URL из запроса или используем дефолтный
            base_url = request.host_url.rstrip('/')
            # Если это localhost, заменяем на реальный URL Render
            if 'localhost' in base_url or '127.0.0.1' in base_url:
                base_url = 'https://attendance-system-rbif.onrender.com'
        else:
            base_url = request.host_url.rstrip('/')
        
        # Создаем URL для сканирования с токеном
        qr_data = f"{base_url}/scan?token={qr_token}"
        
        print(f"🔗 Генерация QR-кода: {qr_data}")
        
        # Генерируем QR-код
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Сохраняем в буфер
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        conn.close()
        
        print(f"✅ QR-код сгенерирован для занятия ID: {class_id}")
        
        return send_file(
            img_buffer,
            mimetype='image/png',
            as_attachment=False
        )
        
    except Exception as e:
        print(f"❌ Ошибка генерации QR-кода: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ================== ОТМЕТКА ПОСЕЩАЕМОСТИ ==================

@app.route('/api/mark_attendance', methods=['POST'])
def mark_attendance():
    """Отметка посещаемости по токену"""
    try:
        data = request.json
        token = data.get('token')
        student_id = data.get('student_id')
        
        if not token or not student_id:
            return jsonify({'success': False, 'error': 'Недостаточно данных'})
        
        conn = get_db()
        c = conn.cursor()
        
        # Находим занятие по токену
        c.execute("SELECT id FROM classes WHERE qr_token = ?", (token,))
        class_data = c.fetchone()
        
        if not class_data:
            return jsonify({'success': False, 'error': 'Неверный QR-код'})
        
        class_id = class_data['id']
        
        # Проверяем, не отметился ли уже студент
        c.execute("SELECT * FROM attendance WHERE student_id = ? AND class_id = ?",
                  (student_id, class_id))
        
        if c.fetchone():
            return jsonify({'success': False, 'error': 'Вы уже отметились'})
        
        # Добавляем запись о посещаемости
        scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            "INSERT INTO attendance (student_id, class_id, status, scan_time) VALUES (?, ?, 'present', ?)",
            (student_id, class_id, scan_time)
        )
        
        conn.commit()
        conn.close()
        
        print(f"✅ Отмечена посещаемость: студент {student_id}, занятие {class_id}")
        
        return jsonify({
            'success': True,
            'message': 'Посещаемость успешно отмечена!'
        })
        
    except Exception as e:
        print(f"❌ Ошибка отметки посещаемости: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ================== УПРАВЛЕНИЕ ПОСЕЩАЕМОСТЬЮ ==================

@app.route('/api/get_attendance/<int:class_id>')
def get_attendance(class_id):
    """Получение посещаемости для занятия"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''SELECT s.id, s.name, s.group_name, 
                            COALESCE(a.status, 'absent') as status,
                            a.scan_time
                     FROM students s
                     LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = ?
                     ORDER BY s.group_name, s.name''', (class_id,))
        
        attendance = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify(attendance)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update_status', methods=['POST'])
def update_status():
    """Ручное изменение статуса посещаемости"""
    try:
        data = request.json
        student_id = data.get('student_id')
        class_id = data.get('class_id')
        status = data.get('status')
        
        if not all([student_id, class_id, status]):
            return jsonify({'success': False, 'error': 'Не все данные указаны'})
        
        conn = get_db()
        c = conn.cursor()
        
        # Обновляем статус
        if status == 'present':
            scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''INSERT OR REPLACE INTO attendance 
                         (student_id, class_id, status, scan_time)
                         VALUES (?, ?, ?, ?)''',
                      (student_id, class_id, status, scan_time))
        else:
            c.execute('''INSERT OR REPLACE INTO attendance 
                         (student_id, class_id, status, scan_time)
                         VALUES (?, ?, ?, NULL)''',
                      (student_id, class_id, status))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Статус обновлен'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ================== ЭКСПОРТ В EXCEL (CSV) ==================

@app.route('/api/export_csv/<int:class_id>')
def export_csv(class_id):
    """Экспорт посещаемости в CSV с русскими статусами"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Получаем данные занятия
        c.execute("SELECT subject, date_time FROM classes WHERE id = ?", (class_id,))
        class_info = c.fetchone()
        
        if not class_info:
            return "Занятие не найдено", 404
        
        # Получаем посещаемость
        c.execute('''SELECT s.name, s.group_name, 
                            COALESCE(a.status, 'absent') as status
                     FROM students s
                     LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = ?
                     ORDER BY s.group_name, s.name''', (class_id,))
        
        attendance = c.fetchall()
        conn.close()
        
        # Создаем CSV в памяти с BOM для русского Excel
        output = io.StringIO()
        
        # Используем точку с запятой как разделитель (лучше для русского Excel)
        writer = csv.writer(output, delimiter=';')
        
        # Заголовки на русском
        writer.writerow(['Предмет', class_info['subject']])
        writer.writerow(['Дата проведения', class_info['date_time']])
        writer.writerow([])  # Пустая строка
        writer.writerow(['Студент', 'Группа', 'Статус посещаемости'])
        
        for row in attendance:
            # Преобразуем статус на русский
            status_ru = {
                'present': 'Присутствовал',
                'absent': 'Отсутствовал', 
                'late': 'Опоздал'
            }.get(row['status'], row['status'])
            
            writer.writerow([
                row['name'],
                row['group_name'],
                status_ru
            ])
        
        output.seek(0)
        
        # Кодируем в UTF-8 с BOM для Excel
        csv_data = output.getvalue().encode('utf-8-sig')
        
        # Создаем имя файла с датой
        date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'посещаемость_{class_info["subject"]}_{date_str}.csv'
        
        return send_file(
            io.BytesIO(csv_data),
            mimetype='text/csv; charset=utf-8-sig',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"❌ Ошибка экспорта: {str(e)}")
        return f"Ошибка экспорта: {str(e)}", 500

# ================== СИСТЕМНЫЕ МАРШРУТЫ ==================

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT 1")
        db_status = "OK"
        conn.close()
    except Exception as e:
        db_status = f"ERROR: {str(e)}"
    
    return jsonify({
        'status': 'running',
        'python_version': os.environ.get('PYTHON_VERSION', 'unknown'),
        'on_render': 'RENDER' in os.environ,
        'database': db_status,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/test_qr/<int:class_id>')
def test_qr(class_id):
    """Тестовый маршрут для проверки QR-кода"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute("SELECT * FROM classes WHERE id = ?", (class_id,))
        class_data = c.fetchone()
        
        if not class_data:
            return jsonify({'error': 'Занятие не найдено'}), 404
        
        # Определяем правильный URL
        if 'RENDER' in os.environ:
            base_url = 'https://attendance-system-rbif.onrender.com'
        else:
            base_url = request.host_url.rstrip('/')
        
        qr_data = f"{base_url}/scan?token={class_data['qr_token']}"
        
        return jsonify({
            'success': True,
            'class_id': class_id,
            'subject': class_data['subject'],
            'qr_token': class_data['qr_token'],
            'qr_data': qr_data,
            'qr_link': f"{base_url}/api/generate_qr/{class_id}"
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ================== ЗАПУСК ПРИЛОЖЕНИЯ ==================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запуск системы контроля посещаемости")
    print(f"📁 Путь к БД: {DB_PATH}")
    print(f"🌐 Порт: {port}")
    print(f"⚙️ Режим: {'PRODUCTION' if 'RENDER' in os.environ else 'DEVELOPMENT'}")
    app.run(host='0.0.0.0', port=port, debug=True)
