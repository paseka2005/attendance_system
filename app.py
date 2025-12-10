from flask import Flask, render_template, request, jsonify, send_file
import sqlite3, os, uuid, qrcode, io, csv
from datetime import datetime

app = Flask(__name__)

# ================== БАЗА ДАННЫХ ==================
def init_db():
    """Инициализация базы данных"""
    db_path = '/tmp/attendance.db' if 'RENDER' in os.environ else 'attendance.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Таблица студентов (3 человека)
    c.execute('''CREATE TABLE IF NOT EXISTS students
                 (id INTEGER PRIMARY KEY, name TEXT, group_name TEXT)''')
    
    # Таблица занятий
    c.execute('''CREATE TABLE IF NOT EXISTS classes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  subject TEXT, date_time TEXT, qr_token TEXT)''')
    
    # Таблица посещаемости
    c.execute('''CREATE TABLE IF NOT EXISTS attendance
                 (student_id INTEGER, class_id INTEGER,
                  status TEXT DEFAULT 'absent', scan_time TEXT,
                  PRIMARY KEY(student_id, class_id))''')
    
    # Добавляем 3 тестовых студента
    students = [
        (1, 'Иван Петров', '101'),
        (2, 'Мария Сидорова', '101'), 
        (3, 'Алексей Иванов', '102')
    ]
    for student in students:
        c.execute("INSERT OR IGNORE INTO students VALUES (?, ?, ?)", student)
    
    conn.commit()
    conn.close()

# Инициализируем БД при старте
init_db()

def get_db():
    """Подключение к БД"""
    db_path = '/tmp/attendance.db' if 'RENDER' in os.environ else 'attendance.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# ================== ГЛАВНЫЕ СТРАНИЦЫ ==================
@app.route('/')
def teacher_page():
    """Страница преподавателя"""
    conn = get_db()
    c = conn.cursor()
    
    # Получаем занятия
    c.execute("SELECT * FROM classes ORDER BY date_time DESC")
    classes = c.fetchall()
    
    # Получаем студентов
    c.execute("SELECT * FROM students")
    students = c.fetchall()
    
    # Посещаемость для последнего занятия
    attendance = []
    if classes:
        c.execute('''SELECT s.id, s.name, s.group_name, 
                            COALESCE(a.status, 'absent') as status
                     FROM students s
                     LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = ?
                     ORDER BY s.group_name, s.name''', (classes[0]['id'],))
        attendance = c.fetchall()
    
    conn.close()
    
    return render_template('index.html', 
                         classes=classes,
                         students=students,
                         attendance=attendance,
                         selected_class=classes[0]['id'] if classes else None)

@app.route('/scan')
def scan_page():
    """Страница сканирования для студентов"""
    return render_template('scan.html')

# ================== API ДЛЯ ЗАНЯТИЙ ==================
@app.route('/api/create_class', methods=['POST'])
def create_class():
    """Создать новое занятие"""
    subject = request.form['subject']
    date_time = request.form['date_time']
    
    conn = get_db()
    c = conn.cursor()
    
    # Генерируем уникальный токен для QR-кода
    qr_token = str(uuid.uuid4())
    
    c.execute("INSERT INTO classes (subject, date_time, qr_token) VALUES (?, ?, ?)",
              (subject, date_time, qr_token))
    
    class_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'class_id': class_id})

# ================== ГЕНЕРАЦИЯ QR-КОДА ==================
@app.route('/api/generate_qr/<int:class_id>')
def generate_qr(class_id):
    """Сгенерировать QR-код для занятия"""
    conn = get_db()
    c = conn.cursor()
    
    # Получаем токен занятия
    c.execute("SELECT qr_token FROM classes WHERE id = ?", (class_id,))
    class_data = c.fetchone()
    
    if not class_data:
        return "Ошибка: занятие не найдено", 404
    
    qr_token = class_data['qr_token']
    
    # Создаем ссылку для отметки
    base_url = request.host_url.rstrip('/')
    qr_data = f"{base_url}/api/mark/{qr_token}"
    
    # Генерируем QR-код
    qr = qrcode.make(qr_data)
    
    # Сохраняем в буфер
    img_buffer = io.BytesIO()
    qr.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    conn.close()
    
    return send_file(img_buffer, mimetype='image/png')

# ================== ОТМЕТКА ПОСЕЩАЕМОСТИ ==================
@app.route('/api/mark/<token>', methods=['POST'])
def mark_attendance(token):
    """Отметить посещаемость"""
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
    
    # Проверяем, не отметился ли уже
    c.execute("SELECT * FROM attendance WHERE student_id = ? AND class_id = ?",
              (student_id, class_id))
    
    if c.fetchone():
        return jsonify({'success': False, 'error': 'Вы уже отметились'})
    
    # Добавляем запись
    scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO attendance VALUES (?, ?, 'present', ?)",
              (student_id, class_id, scan_time))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Посещаемость отмечена!'})

# ================== УПРАВЛЕНИЕ ПОСЕЩАЕМОСТЬЮ ==================
@app.route('/api/get_attendance/<int:class_id>')
def get_attendance(class_id):
    """Получить посещаемость для занятия"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT s.id, s.name, s.group_name, 
                        COALESCE(a.status, 'absent') as status
                 FROM students s
                 LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = ?
                 ORDER BY s.group_name, s.name''', (class_id,))
    
    attendance = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify(attendance)

@app.route('/api/update_status', methods=['POST'])
def update_status():
    """Изменить статус вручную"""
    data = request.json
    student_id = data['student_id']
    class_id = data['class_id']
    status = data['status']
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''INSERT OR REPLACE INTO attendance 
                 (student_id, class_id, status, scan_time)
                 VALUES (?, ?, ?, 
                 CASE WHEN ? = 'present' THEN datetime('now') ELSE NULL END)''',
              (student_id, class_id, status, status))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/export_csv/<int:class_id>')
def export_csv(class_id):
    """Экспорт в CSV"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT c.subject, c.date_time, s.name, s.group_name, 
                        COALESCE(a.status, 'absent') as status
                 FROM classes c, students s
                 LEFT JOIN attendance a ON s.id = a.student_id AND a.class_id = c.id
                 WHERE c.id = ?''', (class_id,))
    
    data = c.fetchall()
    conn.close()
    
    # Создаем CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Предмет', 'Дата', 'Студент', 'Группа', 'Статус'])
    
    for row in data:
        writer.writerow([row['subject'], row['date_time'], 
                        row['name'], row['group_name'], row['status']])
    
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'attendance_{class_id}.csv'
    )

# ================== ЗАПУСК ==================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)