import os
import sqlite3
import uuid
import qrcode
import io
import csv
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory

app = Flask(__name__)

# ================== НАСТРОЙКИ БАЗЫ ДАННЫХ ==================

def init_db():
    """Инициализация базы данных"""
    # На Render используем /tmp папку, локально - текущую папку
    if 'RENDER' in os.environ:
        db_path = '/tmp/attendance.db'
    else:
        db_path = 'attendance.db'
    
    print(f"🔄 Инициализация БД по пути: {db_path}")
    
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
        print("✅ Тестовые студенты добавлены")
    
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
    return render_template('scan.html')

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
            return "Занятие не найдено", 404
        
        # Получаем токен занятия
        qr_token = class_data['qr_token']
        
        # Создаем ссылку для отметки посещаемости
        base_url = request.host_url.rstrip('/')
        qr_data = f"{base_url}/api/mark_attendance/{qr_token}"
        
        # Генерируем QR-код
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
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
        
        print(f"✅ Сгенерирован QR-код для занятия ID: {class_id}")
        
        return send_file(img_buffer, mimetype='image/png')
        
    except Exception as e:
        print(f"❌ Ошибка генерации QR-кода: {str(e)}")
        return f"Ошибка: {str(e)}", 500

# ================== ОТМЕТКА ПОСЕЩАЕМОСТИ ==================

@app.route('/api/mark_attendance/<token>', methods=['POST'])
def mark_attendance(token):
    """Отметка посещаемости по токену из QR-кода"""
    try:
        data = request.json
        student_id = data.get('student_id')
        
        if not student_id:
            return jsonify({'success': False, 'error': 'Выберите студента'})
        
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

# ================== ЭКСПОРТ ДАННЫХ ==================

@app.route('/api/export_csv/<int:class_id>')
def export_csv(class_id):
    """Экспорт посещаемости в CSV"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''SELECT c.subject, c.date_time, s.name, s.group_name, 
                            COALESCE(a.status, 'absent') as status
                     FROM classes c, students s
                     LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = c.id
                     WHERE c.id = ?''', (class_id,))
        
        data = c.fetchall()
        conn.close()
        
        # Создаем CSV в памяти
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Предмет', 'Дата и время', 'Студент', 'Группа', 'Статус'])
        
        for row in data:
            writer.writerow([
                row['subject'],
                row['date_time'],
                row['name'],
                row['group_name'],
                row['status']
            ])
        
        output.seek(0)
        
        # Отправляем файл
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'посещаемость_{class_id}.csv'
        )
        
    except Exception as e:
        return f"Ошибка экспорта: {str(e)}", 500

# ================== СТАТИЧЕСКИЕ ФАЙЛЫ ==================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Обслуживание статических файлов"""
    return send_from_directory('static', filename)

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
        'db_path': DB_PATH
    })

@app.route('/test')
def test_page():
    """Тестовая страница"""
    return """
    <h1>✅ Система контроля посещаемости</h1>
    <p>Приложение запущено и работает!</p>
    <ul>
        <li><a href="/">Главная страница</a></li>
        <li><a href="/scan">Сканирование QR</a></li>
        <li><a href="/health">Проверка здоровья</a></li>
        <li><a href="/api/get_classes">API: список занятий</a></li>
    </ul>
    """

# ================== ЗАПУСК ПРИЛОЖЕНИЯ ==================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запуск приложения на порту {port}")
    print(f"📁 Путь к БД: {DB_PATH}")
    print(f"🌐 Режим: {'PRODUCTION' if 'RENDER' in os.environ else 'DEVELOPMENT'}")
    app.run(host='0.0.0.0', port=port)
