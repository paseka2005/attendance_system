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
            (1, 'Алексей Пасека', 'Группа ИС-311'),
            (2, 'Анна Герасимова', 'Группа ИС-311'),
            (3, 'Максим Криворучко', 'Группа ИС-311')
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
    # Получаем токен из URL (если есть)
    token = request.args.get('token')
    
    # Можно добавить логику для определения мобильного устройства
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(word in user_agent for word in ['mobile', 'android', 'iphone'])
    
    # Передаем токен в шаблон
    return render_template('scan.html', is_mobile=is_mobile, token=token)

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
        
        print(f"✅ Создано занятие: {subject} (ID: {class_id}, токен: {qr_token})")
        
        return jsonify({
            'success': True,
            'class_id': class_id,
            'qr_token': qr_token,
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
            as_attachment=False,
            download_name=f'qr_code_{class_id}.png'
        )
        
    except Exception as e:
        print(f"❌ Ошибка генерации QR-кода: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ================== ОТМЕТКА ПОСЕЩАЕМОСТИ ==================

@app.route('/api/mark_attendance', methods=['POST'])
def mark_attendance():
    """Обработка отметки посещаемости по QR-коду (для студентов)"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'Нет данных в запросе'}), 400
        
        token = data.get('token')
        student_id = data.get('student_id')
        
        print(f"📱 Получена отметка: token={token}, student_id={student_id}")
        
        if not token:
            return jsonify({'success': False, 'error': 'Отсутствует токен QR-кода'}), 400
        
        if not student_id:
            return jsonify({'success': False, 'error': 'Отсутствует ID студента'}), 400
        
        try:
            student_id = int(student_id)
        except ValueError:
            return jsonify({'success': False, 'error': 'Неверный формат ID студента'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Проверяем существование токена
        c.execute("SELECT * FROM classes WHERE qr_token = ?", (token,))
        class_data = c.fetchone()
        
        if not class_data:
            conn.close()
            print(f"❌ Токен не найден: {token}")
            return jsonify({'success': False, 'error': 'Неверный QR-код или занятие не найдено'}), 404
        
        # Проверяем существование студента
        c.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student_data = c.fetchone()
        
        if not student_data:
            conn.close()
            print(f"❌ Студент не найден: {student_id}")
            return jsonify({'success': False, 'error': 'Студент не найден'}), 404
        
        class_id = class_data['id']
        scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Проверяем, была ли уже отметка
        c.execute('''SELECT status FROM attendance 
                     WHERE student_id = ? AND class_id = ?''', 
                  (student_id, class_id))
        existing = c.fetchone()
        
        student_dict = dict(student_data)
        class_dict = dict(class_data)
        
        if existing:
            # Обновляем существующую запись
            c.execute('''UPDATE attendance 
                         SET status = 'present', scan_time = ?
                         WHERE student_id = ? AND class_id = ?''',
                      (scan_time, student_id, class_id))
            message = '✅ Ваше присутствие было обновлено'
            print(f"🔄 Обновлена отметка для студента {student_id} на занятии {class_id}")
        else:
            # Создаем новую запись
            c.execute('''INSERT INTO attendance 
                         (student_id, class_id, status, scan_time)
                         VALUES (?, ?, 'present', ?)''',
                      (student_id, class_id, scan_time))
            message = '✅ Вы успешно отметились на занятии!'
            print(f"✅ Новая отметка: студент {student_id}, занятие {class_id}")
        
        conn.commit()
        conn.close()
        
        print(f"✅ Успешная отметка: студент {student_dict['name']}, предмет {class_dict['subject']}")
        
        return jsonify({
            'success': True,
            'message': message,
            'student': {
                'id': student_dict['id'],
                'name': student_dict['name'],
                'group_name': student_dict['group_name']
            },
            'class': {
                'id': class_dict['id'],
                'subject': class_dict['subject'],
                'date_time': class_dict['date_time']
            },
            'scan_time': scan_time,
            'timestamp': datetime.now().isoformat()
        })
        
    except sqlite3.Error as e:
        print(f"❌ Ошибка базы данных при отметке: {str(e)}")
        return jsonify({'success': False, 'error': f'Ошибка базы данных: {str(e)}'}), 500
        
    except Exception as e:
        print(f"❌ Неожиданная ошибка при отметке посещаемости: {str(e)}")
        return jsonify({'success': False, 'error': f'Внутренняя ошибка сервера: {str(e)}'}), 500

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
    """Ручное изменение статуса посещаемости (для преподавателя)"""
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
            return jsonify({'error': 'Занятие не найдено'}), 404
        
        # Получаем посещаемость
        c.execute('''SELECT s.name, s.group_name, 
                            COALESCE(a.status, 'absent') as status,
                            a.scan_time
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
        writer.writerow(['Студент', 'Группа', 'Статус посещаемости', 'Время отметки'])
        
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
                status_ru,
                row['scan_time'] or ''
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
        return jsonify({'error': str(e)}), 500

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
        'service': 'Attendance System',
        'version': '1.0.0',
        'python_version': os.environ.get('PYTHON_VERSION', 'unknown'),
        'on_render': 'RENDER' in os.environ,
        'database': db_status,
        'timestamp': datetime.now().isoformat(),
        'api_endpoints': {
            'create_class': '/api/create_class',
            'get_classes': '/api/get_classes',
            'mark_attendance': '/api/mark_attendance',
            'generate_qr': '/api/generate_qr/<class_id>',
            'health': '/health'
        }
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
            'qr_link': f"{base_url}/api/generate_qr/{class_id}",
            'scan_url': qr_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test_mark', methods=['GET', 'POST'])
def test_mark():
    """Тестовый эндпоинт для проверки отметки"""
    if request.method == 'GET':
        # Показываем форму для тестирования
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Тест отметки посещаемости</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 600px; margin: 0 auto; }
                input, button { padding: 10px; margin: 5px; }
                .result { margin-top: 20px; padding: 15px; border-radius: 5px; }
                .success { background: #d4edda; color: #155724; }
                .error { background: #f8d7da; color: #721c24; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔧 Тестирование системы отметки</h1>
                
                <h3>Тест 1: Проверка соединения</h3>
                <button onclick="testConnection()">Проверить соединение</button>
                
                <h3>Тест 2: Проверка студента</h3>
                <input type="number" id="studentIdTest" placeholder="ID студента (1-3)" value="1">
                <button onclick="testStudent()">Проверить студента</button>
                
                <h3>Тест 3: Полный тест отметки</h3>
                <input type="text" id="tokenTest" placeholder="Токен QR-кода" style="width: 300px;">
                <input type="number" id="studentIdMark" placeholder="ID студента" value="1">
                <button onclick="testMark()">Тест отметки</button>
                
                <h3>Тест 4: Получить список занятий</h3>
                <button onclick="getClasses()">Получить занятия</button>
                
                <div id="result" class="result"></div>
            </div>
            
            <script>
                function showResult(message, type) {
                    const div = document.getElementById('result');
                    div.textContent = message;
                    div.className = 'result ' + type;
                }
                
                async function testConnection() {
                    try {
                        const response = await fetch('/health');
                        const data = await response.json();
                        showResult(JSON.stringify(data, null, 2), 'success');
                    } catch (error) {
                        showResult('❌ Ошибка: ' + error.message, 'error');
                    }
                }
                
                async function testStudent() {
                    const studentId = document.getElementById('studentIdTest').value;
                    try {
                        const response = await fetch('/api/get_classes');
                        const classes = await response.json();
                        if (classes.length > 0) {
                            showResult(`✅ Занятий найдено: ${classes.length}\\nПервый токен: ${classes[0].qr_token}`, 'success');
                        } else {
                            showResult('⚠️ Занятий нет. Сначала создайте занятие.', 'error');
                        }
                    } catch (error) {
                        showResult('❌ Ошибка: ' + error.message, 'error');
                    }
                }
                
                async function testMark() {
                    const token = document.getElementById('tokenTest').value;
                    const studentId = document.getElementById('studentIdMark').value;
                    
                    if (!token) {
                        showResult('❌ Введите токен', 'error');
                        return;
                    }
                    
                    try {
                        const response = await fetch('/api/mark_attendance', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ token: token, student_id: studentId })
                        });
                        const data = await response.json();
                        showResult(JSON.stringify(data, null, 2), data.success ? 'success' : 'error');
                    } catch (error) {
                        showResult('❌ Ошибка: ' + error.message, 'error');
                    }
                }
                
                async function getClasses() {
                    try {
                        const response = await fetch('/api/get_classes');
                        const data = await response.json();
                        if (data.length > 0) {
                            let html = '<h4>Список занятий:</h4><ul>';
                            data.forEach(cls => {
                                html += `<li>ID: ${cls.id}, Предмет: ${cls.subject}, Токен: ${cls.qr_token}</li>`;
                            });
                            html += '</ul>';
                            document.getElementById('result').innerHTML = html;
                            document.getElementById('tokenTest').value = data[0]?.qr_token || '';
                        } else {
                            showResult('⚠️ Занятий нет. Сначала создайте занятие.', 'error');
                        }
                    } catch (error) {
                        showResult('❌ Ошибка: ' + error.message, 'error');
                    }
                }
                
                // Автозагрузка при открытии
                window.onload = getClasses;
            </script>
        </body>
        </html>
        '''
    else:
        # Эмулируем запрос от QR-сканера
        token = request.form.get('token')
        student_id = request.form.get('student_id')
        
        # Проверяем в БД
        conn = get_db()
        c = conn.cursor()
        
        c.execute("SELECT * FROM classes WHERE qr_token = ?", (token,))
        class_data = c.fetchone()
        
        c.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student_data = c.fetchone()
        
        conn.close()
        
        return jsonify({
            'token_exists': bool(class_data),
            'student_exists': bool(student_data),
            'class_info': dict(class_data) if class_data else None,
            'student_info': dict(student_data) if student_data else None,
            'suggestion': 'Используйте /api/mark_attendance для реальной отметки'
        })

@app.route('/api/get_students')
def get_students():
    """Получение списка всех студентов"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM students ORDER BY group_name, name")
        students = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(students)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify_token/<token>')
def verify_token(token):
    """Проверка валидности токена"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute("SELECT id, subject, date_time FROM classes WHERE qr_token = ?", (token,))
        class_data = c.fetchone()
        
        conn.close()
        
        if class_data:
            return jsonify({
                'valid': True,
                'class': dict(class_data),
                'message': 'Токен действителен'
            })
        else:
            return jsonify({
                'valid': False,
                'message': 'Неверный токен'
            })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ================== ЗАПУСК ПРИЛОЖЕНИЯ ==================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n{'='*50}")
    print(f"🚀 Запуск системы контроля посещаемости")
    print(f"📁 Путь к БД: {DB_PATH}")
    print(f"🌐 Порт: {port}")
    print(f"⚙️ Режим: {'PRODUCTION (Render)' if 'RENDER' in os.environ else 'DEVELOPMENT'}")
    print(f"📊 Студентов в базе: 3 (тестовые данные)")
    print(f"📡 API эндпоинты:")
    print(f"   • Главная страница: /")
    print(f"   • Сканирование: /scan")
    print(f"   • Создание занятия: /api/create_class (POST)")
    print(f"   • Отметка посещаемости: /api/mark_attendance (POST)")
    print(f"   • Генерация QR: /api/generate_qr/<class_id>")
    print(f"   • Проверка здоровья: /health")
    print(f"{'='*50}\n")
    
    app.run(host='0.0.0.0', port=port, debug=('RENDER' not in os.environ))
