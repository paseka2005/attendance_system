import os
import sqlite3
from flask import Flask, render_template, request, jsonify, send_file
import uuid
import qrcode
import io
import csv
from datetime import datetime

app = Flask(__name__)

# ========== ИСПРАВЛЕННАЯ ФУНКЦИЯ БАЗЫ ДАННЫХ ==========
def init_db():
    """Инициализация базы данных с правильным путем на Render"""
    # На Render используем /tmp папку, которая доступна для записи
    if 'RENDER' in os.environ:
        db_path = '/tmp/attendance.db'
        print(f"Используем базу данных на Render: {db_path}")
    else:
        db_path = 'attendance.db'
        print(f"Используем локальную базу: {db_path}")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Таблица студентов
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
    
    # Добавляем тестовых студентов
    students = [
        (1, 'Иван Петров', '101'),
        (2, 'Мария Сидорова', '101'), 
        (3, 'Алексей Иванов', '102')
    ]
    
    for student in students:
        c.execute("INSERT OR IGNORE INTO students VALUES (?, ?, ?)", student)
    
    conn.commit()
    conn.close()
    print("База данных инициализирована")
    return db_path

# Инициализируем БД при старте
DB_PATH = init_db()

def get_db():
    """Подключение к БД с правильным путем"""
    if 'RENDER' in os.environ:
        db_path = '/tmp/attendance.db'
    else:
        db_path = 'attendance.db'
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
