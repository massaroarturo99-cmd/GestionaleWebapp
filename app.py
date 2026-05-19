from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import drive_service
import pdfkit
import csv
from io import StringIO
from flask import Response

app = Flask(__name__)
app.config['DATABASE'] = 'officina.db'
app.secret_key = 'super_secret_key_officina'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_uploads')

# Ensure upload directory exists right away
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS clienti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                telefono TEXT,
                note TEXT
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS veicoli (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                targa TEXT NOT NULL UNIQUE,
                marca TEXT,
                modello TEXT,
                anno TEXT,
                cliente_id INTEGER,
                stato TEXT DEFAULT 'PREVENTIVO',
                data_arrivo DATE,
                data_consegna_prevista DATE,
                lavorazioni_sostituzione TEXT,
                lavorazioni_ripristino TEXT,
                totale REAL DEFAULT 0.0,
                manodopera REAL DEFAULT 0.0,
                costo_ricambi REAL DEFAULT 0.0,
                acconto REAL DEFAULT 0.0,
                riconsegnata BOOLEAN DEFAULT 0,
                drive_folder_id TEXT,
                controparte_nome TEXT,
                controparte_telefono TEXT,
                FOREIGN KEY (cliente_id) REFERENCES clienti (id)
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS ricambi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veicolo_id INTEGER,
                nome TEXT NOT NULL,
                prezzo REAL DEFAULT 0.0,
                ordinato BOOLEAN DEFAULT 0,
                in_carrozzeria BOOLEAN DEFAULT 0,
                bolla_prodotto_id INTEGER,
                FOREIGN KEY (veicolo_id) REFERENCES veicoli (id)
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS lavorazioni_ripristino_righe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veicolo_id INTEGER,
                descrizione TEXT NOT NULL,
                gravita TEXT,
                FOREIGN KEY (veicolo_id) REFERENCES veicoli (id)
            )
        ''')

        # TABELLE FORNITORI E BOLLE
        db.execute('''
            CREATE TABLE IF NOT EXISTS fornitori (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                telefono TEXT,
                note TEXT,
                categoria TEXT DEFAULT 'Materiale'
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS fornitore_prodotti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornitore_id INTEGER,
                nome TEXT NOT NULL,
                prezzo_listino REAL DEFAULT 0.0,
                FOREIGN KEY (fornitore_id) REFERENCES fornitori (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS bolle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornitore_id INTEGER,
                codice TEXT,
                data DATE,
                note TEXT,
                FOREIGN KEY (fornitore_id) REFERENCES fornitori (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS bolla_prodotti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bolla_id INTEGER,
                prodotto_id INTEGER,
                quantita INTEGER DEFAULT 1,
                prezzo_applicato REAL DEFAULT 0.0,
                sconto_perc REAL DEFAULT 0.0,
                nome_ricambio TEXT,
                codice_ricambio TEXT,
                marchio TEXT,
                modello_auto TEXT,
                anno TEXT,
                veicolo_targa TEXT,
                stato_ordine TEXT DEFAULT 'ORDINATO',
                stato_consegna TEXT DEFAULT 'IN OFFICINA',
                FOREIGN KEY (bolla_id) REFERENCES bolle (id),
                FOREIGN KEY (prodotto_id) REFERENCES fornitore_prodotti (id)
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS catalogo_ricambi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codice_ricambio TEXT,
                nome_ricambio TEXT NOT NULL,
                marchio TEXT,
                modello_auto TEXT,
                anno TEXT,
                ultimo_prezzo REAL DEFAULT 0.0
            )
        ''')
        db.commit()

def migrate_db():
    db = get_db()
    try:
        db.execute("SELECT lavorazioni_sostituzione FROM veicoli LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE veicoli ADD COLUMN lavorazioni_sostituzione TEXT")
        db.execute("ALTER TABLE veicoli ADD COLUMN lavorazioni_ripristino TEXT")
        db.execute("ALTER TABLE veicoli ADD COLUMN drive_folder_id TEXT")
        db.commit()

    try:
        db.execute("SELECT bolla_prodotto_id FROM ricambi LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE ricambi ADD COLUMN bolla_prodotto_id INTEGER")
        db.commit()

    try:
        db.execute("SELECT controparte_nome FROM veicoli LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE veicoli ADD COLUMN controparte_nome TEXT")
        db.execute("ALTER TABLE veicoli ADD COLUMN controparte_telefono TEXT")
        db.commit()

    try:
        db.execute("SELECT manodopera FROM veicoli LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE veicoli ADD COLUMN manodopera REAL DEFAULT 0.0")
        db.execute("ALTER TABLE veicoli ADD COLUMN costo_ricambi REAL DEFAULT 0.0")
        # Mantieni il totale esistente assegnandolo alla manodopera per non perdere i dati pregressi
        db.execute("UPDATE veicoli SET manodopera = totale WHERE totale > 0")
        db.commit()

    try:
        db.execute("SELECT id FROM lavorazioni_ripristino_righe LIMIT 1")
    except sqlite3.OperationalError:
        db.execute('''
            CREATE TABLE IF NOT EXISTS lavorazioni_ripristino_righe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veicolo_id INTEGER,
                descrizione TEXT NOT NULL,
                gravita TEXT,
                FOREIGN KEY (veicolo_id) REFERENCES veicoli (id)
            )
        ''')
        db.commit()

    try:
        db.execute("SELECT categoria FROM fornitori LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE fornitori ADD COLUMN categoria TEXT DEFAULT 'Materiale'")
        db.commit()

    try:
        db.execute("SELECT codice_ricambio FROM bolla_prodotti LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN nome_ricambio TEXT")
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN codice_ricambio TEXT")
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN marchio TEXT")
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN modello_auto TEXT")
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN anno TEXT")

    try:
        db.execute("SELECT veicolo_targa FROM bolla_prodotti LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN veicolo_targa TEXT")
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN stato_ordine TEXT DEFAULT 'ORDINATO'")
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN stato_consegna TEXT DEFAULT 'IN OFFICINA'")

    try:
        db.execute("SELECT sconto_perc FROM bolla_prodotti LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE bolla_prodotti ADD COLUMN sconto_perc REAL DEFAULT 0.0")

        db.execute('''
            CREATE TABLE IF NOT EXISTS catalogo_ricambi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codice_ricambio TEXT,
                nome_ricambio TEXT NOT NULL,
                marchio TEXT,
                modello_auto TEXT,
                anno TEXT,
                ultimo_prezzo REAL DEFAULT 0.0
            )
        ''')
        db.commit()

    # Try to verify if fornitori tables exist (migration for older dbs)
    try:
        db.execute("SELECT id FROM fornitori LIMIT 1")
    except sqlite3.OperationalError:
        db.execute('''
            CREATE TABLE IF NOT EXISTS fornitori (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                telefono TEXT,
                note TEXT,
                categoria TEXT DEFAULT 'Materiale'
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS fornitore_prodotti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornitore_id INTEGER,
                nome TEXT NOT NULL,
                prezzo_listino REAL DEFAULT 0.0,
                FOREIGN KEY (fornitore_id) REFERENCES fornitori (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS bolle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornitore_id INTEGER,
                codice TEXT,
                data DATE,
                note TEXT,
                FOREIGN KEY (fornitore_id) REFERENCES fornitori (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS bolla_prodotti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bolla_id INTEGER,
                prodotto_id INTEGER,
                quantita INTEGER DEFAULT 1,
                prezzo_applicato REAL DEFAULT 0.0,
                sconto_perc REAL DEFAULT 0.0,
                nome_ricambio TEXT,
                codice_ricambio TEXT,
                marchio TEXT,
                modello_auto TEXT,
                anno TEXT,
                veicolo_targa TEXT,
                stato_ordine TEXT DEFAULT 'ORDINATO',
                stato_consegna TEXT DEFAULT 'IN OFFICINA',
                FOREIGN KEY (bolla_id) REFERENCES bolle (id),
                FOREIGN KEY (prodotto_id) REFERENCES fornitore_prodotti (id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS catalogo_ricambi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codice_ricambio TEXT,
                nome_ricambio TEXT NOT NULL,
                marchio TEXT,
                modello_auto TEXT,
                anno TEXT,
                ultimo_prezzo REAL DEFAULT 0.0
            )
        ''')
        db.commit()

if not os.path.exists(app.config['DATABASE']):
    init_db()
else:
    migrate_db()


import threading

def format_drive_folder_name(v):
    return f"{v['targa']} {v['marca'] or ''} {v['modello'] or ''} {v['anno'] or ''}".strip().upper()

def sync_db_to_drive(veicolo_id=None):
    def _sync():
        service = drive_service.get_drive_service()
        if service:
            try:
                root_id = drive_service.get_or_create_root_folder(service)
                # Update global DB files
                drive_service.update_veicoli_txt(service, root_id, app.config['DATABASE'])
                drive_service.update_fornitori_txt(service, root_id, app.config['DATABASE'])

                # If specific vehicle modified, update its specific folder text
                if veicolo_id:
                    with app.app_context():
                        db = get_db()
                        v = db.execute('''
                            SELECT v.*, c.nome as cliente_nome, c.telefono as cliente_telefono
                            FROM veicoli v LEFT JOIN clienti c ON v.cliente_id = c.id
                            WHERE v.id = ?
                        ''', (veicolo_id,)).fetchone()

                        if v:
                            folder_name = format_drive_folder_name(v)

                            # Manage folder tracking by ID to handle name changes
                            if v['drive_folder_id']:
                                folder_id = v['drive_folder_id']
                                try:
                                    drive_service.rename_folder(service, folder_id, folder_name)
                                except Exception:
                                    # Fallback if folder was deleted on drive side
                                    folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, folder_name)
                                    db.execute('UPDATE veicoli SET drive_folder_id = ? WHERE id = ?', (folder_id, veicolo_id))
                                    db.commit()
                            else:
                                folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, folder_name)
                                db.execute('UPDATE veicoli SET drive_folder_id = ? WHERE id = ?', (folder_id, veicolo_id))
                                db.commit()

                            # Fetch ripristino_righe
                            ripristino_righe = db.execute('SELECT * FROM lavorazioni_ripristino_righe WHERE veicolo_id = ?', (veicolo_id,)).fetchall()
                            ripristino_str = ""
                            if ripristino_righe:
                                for r in ripristino_righe:
                                    ripristino_str += f" - {r['descrizione']} [{r['gravita']}]\n"
                            else:
                                ripristino_str = v['lavorazioni_ripristino'] or ''

                            content = (
                                f"Targa: {v['targa']}\n"
                                f"Marca/Modello: {v['marca'] or '-'} {v['modello'] or ''}\n"
                                f"Anno: {v['anno'] or '-'}\n"
                                f"Stato: {v['stato']}\n"
                                f"Cliente: {v['cliente_nome'] or 'N/A'}\n"
                                f"Telefono: {v['cliente_telefono'] or 'N/A'}\n"
                                f"Controparte: {v['controparte_nome'] or 'N/A'} (Tel: {v['controparte_telefono'] or 'N/A'})\n"
                                f"Data Arrivo: {v['data_arrivo']}\n"
                                f"Data Consegna Prevista: {v['data_consegna_prevista'] or 'N/A'}\n"
                                f"Totale: € {v['totale']:.2f}\n"
                                f"Acconto: € {v['acconto']:.2f}\n"
                                f"Sostituzione: {v['lavorazioni_sostituzione'] or ''}\n"
                                f"Ripristino: \n{ripristino_str}\n"
                            )
                            drive_service.upload_vehicle_data_txt(service, folder_id, content)

                            # Generate and upload PDF Preventivo
                            try:
                                ricambi = db.execute('SELECT * FROM ricambi WHERE veicolo_id = ?', (veicolo_id,)).fetchall()

                                # Retrieve photo count for background sync
                                foto_count = 0
                                if v['drive_folder_id']:
                                    try:
                                        photos = drive_service.list_photos(service, v['drive_folder_id'])
                                        foto_count = len(photos)
                                    except Exception as e:
                                        print("Failed to load photos count for PDF sync:", e)

                                # In the background thread context, we need to pass the base_url or absolute path
                                # to render_template so that pdfkit can find local images. But app_context is available.
                                import datetime
                                now = datetime.datetime.now()

                                # Prepare context for the exact variables expected by template_pdf_drive.html
                                import html
                                ripristino_html = ""
                                if ripristino_righe:
                                    ripristino_html = "<ul style='margin:0; padding-left:15px; list-style-type:disc;'>"
                                    for r in ripristino_righe:
                                        safe_desc = html.escape(r['descrizione'] or '')
                                        safe_gravita = html.escape(r['gravita'] or '')
                                        ripristino_html += f"<li>{safe_desc} <strong>[{safe_gravita}]</strong></li>"
                                    ripristino_html += "</ul>"

                                html_content = render_template('template_pdf_drive.html',
                                    data_odierna=now.strftime('%d/%m/%Y'),
                                    pratica_id=v['id'],
                                    anno=v['data_arrivo'][:4] if v['data_arrivo'] else '2024',
                                    targa=v['targa'],
                                    marca=v['marca'] or '-',
                                    modello=v['modello'] or '',
                                    data_arrivo=v['data_arrivo'] or '-',
                                    data_consegna=v['data_consegna_prevista'] or '-',
                                    nome_cliente=v['cliente_nome'] or '_____________________',
                                    telefono_cliente=v['cliente_telefono'] or '_____________________',
                                    testo_sostituzione=v['lavorazioni_sostituzione'] or '',
                                    testo_ripristino_html=ripristino_html,
                                    testo_ripristino=v['lavorazioni_ripristino'] or '',
                                    ricambi=ricambi,
                                    manodopera="{:.2f}".format(v['manodopera'] or 0),
                                    costo_ricambi="{:.2f}".format(v['costo_ricambi'] or 0),
                                    totale="{:.2f}".format(v['totale'] or 0),
                                    acconto="{:.2f}".format(v['acconto'] or 0),
                                    saldo="{:.2f}".format((v['totale'] or 0) - (v['acconto'] or 0)),
                                    foto_count=foto_count
                                )

                                # Replace relative static path with absolute local path for pdfkit to work without server running
                                import os
                                root_path = app.root_path
                                # In Windows, a path might look like C:\app\static. We need it as file:///C:/app/static/
                                file_url_prefix = f"file:///{root_path.replace(os.sep, '/').lstrip('/')}/static/"
                                html_content = html_content.replace('src="/static/', f'src="{file_url_prefix}')

                                options = {
                                    'enable-local-file-access': None,
                                    'print-media-type': None,
                                    'margin-top': '0.5cm',
                                    'margin-right': '0.5cm',
                                    'margin-bottom': '0.5cm',
                                    'margin-left': '0.5cm',
                                    'encoding': "UTF-8"
                                }

                                # Setup wkhtmltopdf configuration for Windows cross-compatibility if needed
                                # It falls back to default if the path doesn't exist
                                wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
                                config = None
                                if os.path.exists(wkhtmltopdf_path):
                                    config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

                                try:
                                    pdf_bytes = pdfkit.from_string(html_content, False, options=options, configuration=config)
                                    print(f"PDF generato con successo. Dimensione: {len(pdf_bytes)} bytes")
                                except Exception as e:
                                    print(f"Errore PDFkit: {e}")
                                    pdf_bytes = None

                                if pdf_bytes:
                                    drive_service.upload_vehicle_pdf(service, folder_id, pdf_bytes, filename=f"Preventivo_{v['targa']}.pdf")
                            except Exception as pdf_e:
                                print("Failed to process PDF block:", pdf_e)

            except Exception as e:
                print("Failed to sync DB to drive:", e)

    # Run the sync in a background thread to prevent blocking the UI
    thread = threading.Thread(target=_sync)
    thread.start()

@app.route('/')
def home():
    db = get_db()
    totale_veicoli = db.execute('SELECT COUNT(*) as count FROM veicoli').fetchone()['count']
    veicoli_sospesi = db.execute('SELECT COUNT(*) as count FROM veicoli WHERE stato = "SOSPESO"').fetchone()['count']
    preventivi = db.execute('SELECT COUNT(*) as count FROM veicoli WHERE stato = "PREVENTIVO"').fetchone()['count']
    lavorazioni_attive = db.execute('SELECT COUNT(*) as count FROM veicoli WHERE stato = "IN LAVORAZIONE"').fetchone()['count']
    veicoli_presenti = db.execute('SELECT COUNT(*) as count FROM veicoli WHERE stato = "IN LAVORAZIONE"').fetchone()['count']

    veicoli_attivi = db.execute("SELECT id, targa, marca, modello FROM veicoli WHERE riconsegnata = 0 ORDER BY targa ASC").fetchall()

    return render_template('home.html',
                           totale_veicoli=totale_veicoli,
                           veicoli_sospesi=veicoli_sospesi,
                           preventivi=preventivi,
                           lavorazioni_attive=lavorazioni_attive,
                           veicoli_presenti=veicoli_presenti,
                           veicoli_attivi=veicoli_attivi)

@app.route('/api/upload_temp', methods=['POST'])
def upload_temp_photos():
    files = request.files.getlist('foto')
    if not files or files[0].filename == '':
        return jsonify({'error': 'Nessun file selezionato'}), 400

    service = drive_service.get_drive_service()
    if not service:
        return jsonify({'error': 'Google Drive non configurato'}), 500

    temp_folder_id = drive_service.get_or_create_temp_folder(service)
    uploaded_files = []

    for file in files:
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # Generate a consistent name for temp photos
            now_str = datetime.now().strftime('%d_%m_%Y_%H_%M_%S')
            final_filename = f"TEMP_{now_str}_{filename}"

            try:
                uploaded = drive_service.upload_photo(service, temp_folder_id, filepath, final_filename)
                if uploaded:
                    uploaded_files.append(uploaded)
            except Exception as e:
                print(f"Errore upload temp foto: {e}")
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)

    return jsonify({'success': True, 'uploaded': len(uploaded_files), 'uploaded_ids': uploaded_files})

@app.route('/api/temp_photos', methods=['GET'])
def get_temp_photos():
    service = drive_service.get_drive_service()
    if not service:
        return jsonify({'error': 'Google Drive non configurato'}), 500

    temp_folder_id = drive_service.get_or_create_temp_folder(service)
    photos = drive_service.list_photos(service, temp_folder_id)
    return jsonify({'photos': photos})

@app.route('/api/assign_temp_photos', methods=['POST'])
def assign_temp_photos():
    data = request.json
    veicolo_id = data.get('veicolo_id')
    photo_ids = data.get('photo_ids', [])

    if not veicolo_id or not photo_ids:
        return jsonify({'error': 'Dati mancanti'}), 400

    db = get_db()
    veicolo = db.execute('SELECT targa FROM veicoli WHERE id = ?', (veicolo_id,)).fetchone()
    if not veicolo:
        return jsonify({'error': 'Veicolo non trovato'}), 404

    service = drive_service.get_drive_service()
    if not service:
        return jsonify({'error': 'Google Drive non configurato'}), 500

    root_id = drive_service.get_or_create_root_folder(service)
    target_folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, veicolo['targa'].upper())

    moved = 0
    for file_id in photo_ids:
        try:
            drive_service.move_file(service, file_id, target_folder_id)
            moved += 1
        except Exception as e:
            print(f"Errore spostamento file {file_id}: {e}")

    return jsonify({'success': True, 'moved': moved})

@app.route('/api/delete_temp_photos', methods=['POST'])
def delete_temp_photos():
    data = request.json
    photo_ids = data.get('photo_ids', [])

    if not photo_ids:
        return jsonify({'error': 'Dati mancanti'}), 400

    service = drive_service.get_drive_service()
    if not service:
        return jsonify({'error': 'Google Drive non configurato'}), 500

    deleted = 0
    for file_id in photo_ids:
        try:
            drive_service.delete_photo(service, file_id)
            deleted += 1
        except Exception as e:
            print(f"Errore eliminazione file {file_id}: {e}")

    return jsonify({'success': True, 'deleted': deleted})

@app.route('/api/preview_drive_image/<file_id>')
def preview_drive_image(file_id):
    service = drive_service.get_drive_service()
    if not service:
        return "Drive non configurato", 500

    try:
        request_download = service.files().get_media(fileId=file_id)
        import io
        from googleapiclient.http import MediaIoBaseDownload
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request_download)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        fh.seek(0)
        return Response(fh.read(), mimetype='image/jpeg')
    except Exception as e:
        print(f"Errore download preview: {e}")
        return "Errore immagine", 500

@app.route('/veicoli')
def veicoli_list():
    db = get_db()
    filtro = request.args.get('filtro', 'tutti')
    ordinamento = request.args.get('ord', 'data')

    query = 'SELECT v.*, c.nome as cliente_nome FROM veicoli v LEFT JOIN clienti c ON v.cliente_id = c.id '
    params = []

    if filtro == 'preventivi':
        query += 'WHERE v.stato = "PREVENTIVO" '
    elif filtro == 'sospesi':
        query += 'WHERE v.stato = "SOSPESO" '
    elif filtro == 'pagamenti':
        query += 'WHERE v.riconsegnata = 1 AND v.totale != v.acconto '
    elif filtro == 'lavorazione':
        query += 'WHERE v.stato = "IN LAVORAZIONE" '
    elif filtro == 'saldati':
        query += 'WHERE v.stato = "SALDATO" '

    if ordinamento == 'targa':
        query += 'ORDER BY v.targa ASC'
    elif ordinamento == 'marca':
        query += 'ORDER BY v.marca ASC, v.modello ASC'
    else:
        query += 'ORDER BY v.data_arrivo DESC, v.id DESC'

    veicoli = db.execute(query, params).fetchall()
    return render_template('veicoli.html', veicoli=veicoli, filtro=filtro, ordinamento=ordinamento)


@app.context_processor
def inject_notifications():
    db = get_db()
    today_date = datetime.now().date()

    # We load all vehicles that are not completed and have a delivery date
    veicoli = db.execute('''
        SELECT id, targa, marca, modello, data_consegna_prevista
        FROM veicoli
        WHERE riconsegnata = 0 AND data_consegna_prevista IS NOT NULL AND data_consegna_prevista != ''
    ''').fetchall()

    notifications = {
        'ritardo': [],
        'oggi': [],
        'domani': []
    }

    for v in veicoli:
        try:
            d_consegna = datetime.strptime(v['data_consegna_prevista'], '%Y-%m-%d').date()
            diff = (d_consegna - today_date).days

            nome_v = f"{v['targa']} - {v['marca'] or ''} {v['modello'] or ''}".strip()
            notifica_item = {'id': v['id'], 'nome': nome_v}

            if diff < 0:
                notifications['ritardo'].append(notifica_item)
            elif diff == 0:
                notifications['oggi'].append(notifica_item)
            elif diff == 1:
                notifications['domani'].append(notifica_item)
        except ValueError:
            pass # Invalid date format

    total_notifications = len(notifications['ritardo']) + len(notifications['oggi']) + len(notifications['domani'])

    return dict(notifications=notifications, total_notifications=total_notifications)


@app.route('/veicolo/nuovo', methods=['GET', 'POST'])
def veicolo_nuovo():
    db = get_db()
    if request.method == 'POST':
        targa = (request.form.get('targa') or '').upper()
        marca = (request.form.get('marca') or '').upper()
        modello = (request.form.get('modello') or '').upper()
        data_arrivo = request.form.get('data_arrivo') or datetime.now().strftime('%Y-%m-%d')
        stato = request.form.get('stato', 'PREVENTIVO')

        controparte_nome = (request.form.get('controparte_nome') or '').upper()
        controparte_telefono = request.form.get('controparte_telefono')

        client_mode = request.form.get('client_mode', 'select')
        cliente_id = None

        if client_mode == 'select':
            cliente_id = request.form.get('cliente_id') or None
        elif client_mode == 'new':
            nome = (request.form.get('nuovo_cliente_nome') or '').upper()
            telefono = request.form.get('nuovo_cliente_telefono')
            if nome:
                cursor_c = db.execute('INSERT INTO clienti (nome, telefono) VALUES (?, ?)', (nome, telefono))
                cliente_id = cursor_c.lastrowid

        try:
            cursor = db.execute('''
                INSERT INTO veicoli (targa, marca, modello, cliente_id, stato, data_arrivo, controparte_nome, controparte_telefono)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (targa, marca, modello, cliente_id, stato, data_arrivo, controparte_nome, controparte_telefono))
            db.commit()

            nuovo_veicolo_id = cursor.lastrowid

            # Sync to drive creates the actual vehicle folder and updates texts
            sync_db_to_drive(nuovo_veicolo_id)

            # Trasloco automatico: sposta SOLO le foto caricate in questa sessione da Temp_Officina
            temp_ids_str = request.form.get('temp_file_ids')
            if temp_ids_str:
                service = drive_service.get_drive_service()
                if service:
                    try:
                        root_id = drive_service.get_or_create_root_folder(service)

                        v = db.execute('SELECT * FROM veicoli WHERE id = ?', (nuovo_veicolo_id,)).fetchone()
                        folder_name = format_drive_folder_name(v)
                        target_folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, folder_name)

                        # Extract list of IDs directly and move only those
                        photo_ids = [pid.strip() for pid in temp_ids_str.split(',') if pid.strip()]
                        for photo_id in photo_ids:
                            file_moved = drive_service.move_file(service, photo_id, target_folder_id)
                            # Rename the file to replace TEMP_ or temp_ with the actual Targa
                            try:
                                file_info = service.files().get(fileId=photo_id, fields='name').execute()
                                old_name = file_info.get('name', '')
                                if old_name.upper().startswith('TEMP_'):
                                    new_name = old_name[5:] # Remove TEMP_
                                    new_name = f"{targa}_{new_name}"
                                    drive_service.rename_file(service, photo_id, new_name)
                            except Exception as re:
                                print(f"Errore durante rinominazione file {photo_id}:", re)

                    except Exception as e:
                        print("Errore durante lo spostamento mirato delle foto da Temp:", e)

            return redirect(url_for('veicolo_detail', id=nuovo_veicolo_id, from_new=1))
        except sqlite3.IntegrityError:
            db.rollback()
            clienti = db.execute('SELECT * FROM clienti ORDER BY nome').fetchall()
            return render_template('veicolo_form.html', error="Targa già presente!", clienti=clienti)

    clienti = db.execute('SELECT * FROM clienti ORDER BY nome').fetchall()
    return render_template('veicolo_form.html', clienti=clienti, veicolo=None)


@app.route('/veicolo/<int:id>', methods=['GET', 'POST'])
def veicolo_detail(id):
    db = get_db()

    if request.method == 'POST':
        referrer = request.form.get('referrer', '/veicoli')
        marca = (request.form.get('marca') or '').upper()
        modello = (request.form.get('modello') or '').upper()
        anno = request.form.get('anno')
        cliente_id = request.form.get('cliente_id') or None
        stato = request.form.get('stato')
        data_arrivo = request.form.get('data_arrivo')
        data_consegna_prevista = request.form.get('data_consegna_prevista')
        lavorazioni_sostituzione = request.form.get('lavorazioni_sostituzione')
        lavorazioni_ripristino = request.form.get('lavorazioni_ripristino')
        manodopera = float(request.form.get('manodopera') or 0.0)
        costo_ricambi = float(request.form.get('costo_ricambi') or 0.0)
        totale = manodopera + costo_ricambi
        acconto = float(request.form.get('acconto') or 0.0)
        riconsegnata = 1 if request.form.get('riconsegnata') else 0

        controparte_nome = (request.form.get('controparte_nome') or '').upper()
        controparte_telefono = request.form.get('controparte_telefono')

        # Auto-update status based on delivery and totals
        if riconsegnata == 1:
            if acconto == totale and totale > 0:
                stato = 'SALDATO'
            elif acconto != totale:
                stato = 'SOSPESO'
        else:
            if acconto == totale and totale > 0:
                stato = 'SALDATO'

        db.execute('''
            UPDATE veicoli SET
                marca=?, modello=?, anno=?, cliente_id=?, stato=?, data_arrivo=?,
                data_consegna_prevista=?, lavorazioni_sostituzione=?, lavorazioni_ripristino=?,
                manodopera=?, costo_ricambi=?, totale=?, acconto=?, riconsegnata=?, controparte_nome=?, controparte_telefono=?
            WHERE id=?
        ''', (marca, modello, anno, cliente_id, stato, data_arrivo, data_consegna_prevista,
              lavorazioni_sostituzione, lavorazioni_ripristino, manodopera, costo_ricambi, totale, acconto, riconsegnata, controparte_nome, controparte_telefono, id))

        # Save Lavorazioni Ripristino Righe (SF/L/M/G)
        db.execute('DELETE FROM lavorazioni_ripristino_righe WHERE veicolo_id = ?', (id,))
        rip_desc = request.form.getlist('rip_desc[]')
        rip_gravita = request.form.getlist('rip_gravita[]')

        for desc, gravita in zip(rip_desc, rip_gravita):
            if desc.strip():
                db.execute('INSERT INTO lavorazioni_ripristino_righe (veicolo_id, descrizione, gravita) VALUES (?, ?, ?)',
                          (id, desc.strip(), gravita))

        db.commit()
        sync_db_to_drive(id)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'success'})

        return redirect(referrer)

    veicolo = db.execute('''
        SELECT v.*, c.nome as cliente_nome, c.telefono as cliente_telefono
        FROM veicoli v LEFT JOIN clienti c ON v.cliente_id = c.id
        WHERE v.id = ?
    ''', (id,)).fetchone()

    if not veicolo:
        return redirect(url_for('veicoli_list'))

    ricambi = db.execute('SELECT * FROM ricambi WHERE veicolo_id = ?', (id,)).fetchall()
    ripristino_righe = db.execute('SELECT * FROM lavorazioni_ripristino_righe WHERE veicolo_id = ?', (id,)).fetchall()
    clienti = db.execute('SELECT * FROM clienti ORDER BY nome').fetchall()

    # Load photos from Drive
    photos = []
    service = drive_service.get_drive_service()
    if service:
        try:
            root_id = drive_service.get_or_create_root_folder(service)
            folder_name = format_drive_folder_name(veicolo)
            if veicolo['drive_folder_id']:
                folder_id = veicolo['drive_folder_id']
            else:
                folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, folder_name)
                db.execute('UPDATE veicoli SET drive_folder_id = ? WHERE id = ?', (folder_id, id))
                db.commit()
            photos = drive_service.list_photos(service, folder_id)
        except Exception as e:
            print("Failed to load photos:", e)

    return render_template('veicolo_detail.html', veicolo=veicolo, ricambi=ricambi, clienti=clienti, photos=photos, ripristino_righe=ripristino_righe)


@app.route('/veicolo/<int:id>/elimina', methods=['POST'])
def veicolo_elimina(id):
    db = get_db()
    db.execute('DELETE FROM ricambi WHERE veicolo_id = ?', (id,))
    db.execute('DELETE FROM veicoli WHERE id = ?', (id,))
    db.commit()
    sync_db_to_drive()
    return redirect(url_for('veicoli_list'))


@app.route('/veicolo/<int:id>/foto', methods=['POST'])
def veicolo_foto_upload(id):
    db = get_db()
    veicolo = db.execute('SELECT * FROM veicoli WHERE id = ?', (id,)).fetchone()
    if not veicolo:
        return redirect(url_for('veicoli_list'))

    service = drive_service.get_drive_service()
    if service and 'foto' in request.files:
        files = request.files.getlist('foto')
        root_id = drive_service.get_or_create_root_folder(service)

        folder_name = format_drive_folder_name(veicolo)
        if veicolo['drive_folder_id']:
            folder_id = veicolo['drive_folder_id']
        else:
            folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, folder_name)
            db.execute('UPDATE veicoli SET drive_folder_id = ? WHERE id = ?', (folder_id, id))
            db.commit()

        now = datetime.now()
        timestamp = now.strftime('%d_%m_%Y_%H_%M')
        for i, file in enumerate(files, start=1):
            if file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
                targa_pulita = (veicolo['targa'] or 'ND').strip().upper()
                new_filename = f"{targa_pulita}_{timestamp}_{i}.{ext}"
                filename = secure_filename(new_filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                drive_service.upload_photo(service, folder_id, filepath, filename)
                os.remove(filepath)

    return redirect(url_for('veicolo_detail', id=id))

@app.route('/veicolo/<int:id>/foto_veloce', methods=['POST'])
def veicolo_foto_veloce(id):
    db = get_db()
    veicolo = db.execute('SELECT * FROM veicoli WHERE id = ?', (id,)).fetchone()
    if not veicolo:
        return redirect(url_for('veicoli_list'))

    service = drive_service.get_drive_service()
    if service and 'foto' in request.files:
        files = request.files.getlist('foto')
        root_id = drive_service.get_or_create_root_folder(service)

        folder_name = format_drive_folder_name(veicolo)
        if veicolo['drive_folder_id']:
            folder_id = veicolo['drive_folder_id']
        else:
            folder_id = drive_service.get_or_create_vehicle_folder(service, root_id, folder_name)
            db.execute('UPDATE veicoli SET drive_folder_id = ? WHERE id = ?', (folder_id, id))
            db.commit()

        now = datetime.now()
        timestamp = now.strftime('%d_%m_%Y_%H_%M')
        for i, file in enumerate(files, start=1):
            if file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
                targa_pulita = (veicolo['targa'] or 'ND').strip().upper()
                new_filename = f"{targa_pulita}_{timestamp}_{i}.{ext}"
                filename = secure_filename(new_filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                drive_service.upload_photo(service, folder_id, filepath, filename)
                os.remove(filepath)

    return redirect(request.referrer or url_for('veicoli_list'))


@app.route('/veicolo/<int:id>/foto/elimina', methods=['POST'])
def veicolo_foto_elimina(id):
    file_id = request.form.get('file_id')
    service = drive_service.get_drive_service()
    if service and file_id:
        try:
            drive_service.delete_photo(service, file_id)
        except Exception as e:
            print("Failed to delete photo:", e)
    return redirect(url_for('veicolo_detail', id=id))


@app.route('/veicolo/<int:id>/stampa')
def veicolo_stampa(id):
    db = get_db()
    tipo = request.args.get('tipo', 'cliente')
    veicolo = db.execute('''
        SELECT v.*, c.nome as cliente_nome, c.telefono as cliente_telefono
        FROM veicoli v LEFT JOIN clienti c ON v.cliente_id = c.id
        WHERE v.id = ?
    ''', (id,)).fetchone()
    if not veicolo:
        return redirect(url_for('veicoli_list'))
    ricambi = db.execute('SELECT * FROM ricambi WHERE veicolo_id = ?', (id,)).fetchall()
    ripristino_righe = db.execute('SELECT * FROM lavorazioni_ripristino_righe WHERE veicolo_id = ?', (id,)).fetchall()

    # Calculate photo count from Google Drive (as we don't store them in db)
    foto_count = 0
    service = drive_service.get_drive_service()
    if service and veicolo['drive_folder_id']:
        try:
            photos = drive_service.list_photos(service, veicolo['drive_folder_id'])
            foto_count = len(photos)
        except Exception as e:
            print("Failed to load photos count:", e)

    return render_template('stampa_veicolo.html', veicolo=veicolo, ricambi=ricambi, tipo=tipo, ripristino_righe=ripristino_righe, foto_count=foto_count)


# ================= RICAMBI ================= #

@app.route('/ricambi')
def ricambi_list():
    db = get_db()
    query = '''
        SELECT r.*, v.targa, v.marca, v.modello
        FROM ricambi r
        LEFT JOIN veicoli v ON r.veicolo_id = v.id
        ORDER BY r.id DESC
    '''
    ricambi = db.execute(query).fetchall()
    veicoli = db.execute('SELECT id, targa, marca, modello FROM veicoli WHERE riconsegnata = 0').fetchall()
    return render_template('ricambi.html', ricambi=ricambi, veicoli=veicoli)

@app.route('/ricambio/nuovo', methods=['POST'])
def ricambio_nuovo():
    db = get_db()
    veicolo_id = request.form.get('veicolo_id') or None
    nome = request.form.get('nome')
    prezzo = float(request.form.get('prezzo') or 0.0)
    ordinato = 1 if request.form.get('ordinato') else 0
    in_carrozzeria = 1 if request.form.get('in_carrozzeria') else 0

    db.execute('''
        INSERT INTO ricambi (veicolo_id, nome, prezzo, ordinato, in_carrozzeria)
        VALUES (?, ?, ?, ?, ?)
    ''', (veicolo_id, nome, prezzo, ordinato, in_carrozzeria))
    db.commit()

    ref = request.form.get('ref', 'ricambi_list')
    if ref == 'veicolo' and veicolo_id:
        return redirect(url_for('veicolo_detail', id=veicolo_id))
    return redirect(url_for('ricambi_list'))

@app.route('/ricambio/<int:id>/elimina', methods=['POST'])
def ricambio_elimina(id):
    db = get_db()
    ref = request.form.get('ref', 'ricambi_list')
    veicolo_id = request.form.get('veicolo_id')

    db.execute('DELETE FROM ricambi WHERE id = ?', (id,))
    db.commit()

    if ref == 'veicolo' and veicolo_id:
        return redirect(url_for('veicolo_detail', id=veicolo_id))
    return redirect(url_for('ricambi_list'))

@app.route('/ricambio/<int:id>/toggle/<campo>', methods=['POST'])
def ricambio_toggle(id, campo):
    db = get_db()
    if campo in ['ordinato', 'in_carrozzeria']:
        ricambio = db.execute(f'SELECT {campo} FROM ricambi WHERE id = ?', (id,)).fetchone()
        nuovo_val = 0 if ricambio[campo] else 1
        query = f'UPDATE ricambi SET {campo} = ? WHERE id = ?'
        db.execute(query, (nuovo_val, id))

        # Se viene segnato come in_carrozzeria, automaticamente segna anche ordinato
        if campo == 'in_carrozzeria' and nuovo_val == 1:
            db.execute('UPDATE ricambi SET ordinato = 1 WHERE id = ?', (id,))

        db.commit()

    ref = request.form.get('ref', 'ricambi_list')
    veicolo_id = request.form.get('veicolo_id')

    if ref == 'veicolo' and veicolo_id:
        return redirect(url_for('veicolo_detail', id=veicolo_id))
    return redirect(url_for('ricambi_list'))


# ================= RUBRICA CLIENTI ================= #

@app.route('/clienti')
def clienti_list():
    db = get_db()
    clienti = db.execute('SELECT * FROM clienti ORDER BY nome').fetchall()
    return render_template('rubrica.html', clienti=clienti)

@app.route('/cliente/nuovo', methods=['POST'])
def cliente_nuovo():
    db = get_db()
    nome = (request.form.get('nome') or '').upper()
    telefono = request.form.get('telefono')
    note = request.form.get('note')

    db.execute('INSERT INTO clienti (nome, telefono, note) VALUES (?, ?, ?)', (nome, telefono, note))
    db.commit()
    return redirect(url_for('clienti_list'))

@app.route('/cliente/<int:id>/aggiorna', methods=['POST'])
def cliente_aggiorna(id):
    db = get_db()
    nome = (request.form.get('nome') or '').upper()
    telefono = request.form.get('telefono')
    note = request.form.get('note')

    db.execute('UPDATE clienti SET nome=?, telefono=?, note=? WHERE id=?', (nome, telefono, note, id))
    db.commit()
    return redirect(url_for('clienti_list'))

@app.route('/cliente/<int:id>/elimina', methods=['POST'])
def cliente_elimina(id):
    db = get_db()
    db.execute('UPDATE veicoli SET cliente_id = NULL WHERE cliente_id = ?', (id,))
    db.execute('DELETE FROM clienti WHERE id = ?', (id,))
    db.commit()
    return redirect(url_for('clienti_list'))

# ================= FORNITORI E BOLLE ================= #

@app.route('/fornitori')
def fornitori_list():
    db = get_db()
    fornitori = db.execute('SELECT * FROM fornitori ORDER BY nome').fetchall()
    return render_template('fornitori.html', fornitori=fornitori)

@app.route('/fornitore/nuovo', methods=['POST'])
def fornitore_nuovo():
    db = get_db()
    nome = (request.form.get('nome') or '').upper()
    telefono = request.form.get('telefono')
    note = request.form.get('note')
    categoria = request.form.get('categoria') or 'Materiale'

    cursor = db.execute('INSERT INTO fornitori (nome, telefono, note, categoria) VALUES (?, ?, ?, ?)', (nome, telefono, note, categoria))
    db.commit()
    return redirect(url_for('fornitore_detail', id=cursor.lastrowid))

@app.route('/fornitore/<int:id>/modifica', methods=['POST'])
def fornitore_modifica(id):
    db = get_db()
    nome = (request.form.get('nome') or '').upper()
    telefono = request.form.get('telefono')
    note = request.form.get('note')
    categoria = request.form.get('categoria') or 'Materiale'
    db.execute('UPDATE fornitori SET nome = ?, telefono = ?, note = ?, categoria = ? WHERE id = ?', (nome, telefono, note, categoria, id))
    db.commit()
    return redirect(url_for('fornitore_detail', id=id))

@app.route('/fornitore/<int:id>')
def fornitore_detail(id):
    db = get_db()
    fornitore = db.execute('SELECT * FROM fornitori WHERE id = ?', (id,)).fetchone()
    if not fornitore:
        return redirect(url_for('fornitori_list'))

    prodotti = db.execute('SELECT * FROM fornitore_prodotti WHERE fornitore_id = ? ORDER BY nome', (id,)).fetchall()
    bolle = db.execute('SELECT * FROM bolle WHERE fornitore_id = ? ORDER BY data DESC, id DESC', (id,)).fetchall()

    # Calculate totals for each bolla
    bolle_with_totals = []
    totale_assoluto = 0.0
    for b in bolle:
        tot = db.execute('SELECT SUM(quantita * prezzo_applicato * (1 - COALESCE(sconto_perc, 0) / 100.0)) as tot FROM bolla_prodotti WHERE bolla_id = ?', (b['id'],)).fetchone()['tot'] or 0.0
        b_dict = dict(b)
        b_dict['totale'] = tot
        totale_assoluto += tot
        bolle_with_totals.append(b_dict)

    # Analisi Spesa: Mese Corrente e Mese Precedente
    now = datetime.now()
    current_month_str = now.strftime('%Y-%m')

    # Calcolo Mese Precedente
    if now.month == 1:
        prev_month = 12
        prev_year = now.year - 1
    else:
        prev_month = now.month - 1
        prev_year = now.year
    prev_month_str = f"{prev_year}-{prev_month:02d}"

    spesa_mese_corrente = 0.0
    spesa_mese_precedente = 0.0

    # Storico Mesi (Totali per ogni mese)
    storico_mesi = {}

    for b in bolle_with_totals:
        if b['data']:
            mese_bolla = b['data'][:7] # YYYY-MM
            storico_mesi[mese_bolla] = storico_mesi.get(mese_bolla, 0.0) + b['totale']

            if mese_bolla == current_month_str:
                spesa_mese_corrente += b['totale']
            elif mese_bolla == prev_month_str:
                spesa_mese_precedente += b['totale']

    variazione_perc = 0.0
    if spesa_mese_precedente > 0:
        variazione_perc = ((spesa_mese_corrente - spesa_mese_precedente) / spesa_mese_precedente) * 100

    storico_mesi_sorted = dict(sorted(storico_mesi.items(), reverse=True))

    # Analisi Consumi per Prodotto
    consumi_query = """
        SELECT COALESCE(fp.id, bp.codice_ricambio, bp.nome_ricambio) as prodotto_id, COALESCE(fp.nome, bp.nome_ricambio) as prodotto, strftime('%Y-%m', b.data) as mese, SUM(bp.quantita) as totale_quantita
        FROM bolla_prodotti bp
        JOIN bolle b ON bp.bolla_id = b.id
        LEFT JOIN fornitore_prodotti fp ON bp.prodotto_id = fp.id
        WHERE b.fornitore_id = ? AND b.data IS NOT NULL
        GROUP BY prodotto_id, prodotto, mese
        ORDER BY prodotto, mese DESC
    """
    consumi_raw = db.execute(consumi_query, (id,)).fetchall()

    # Consumi ultimi 7 giorni
    sette_giorni_fa = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    consumi_7g_query = """
        SELECT COALESCE(fp.id, bp.codice_ricambio, bp.nome_ricambio) as prodotto_id, SUM(bp.quantita) as quantita_7g
        FROM bolla_prodotti bp
        JOIN bolle b ON bp.bolla_id = b.id
        LEFT JOIN fornitore_prodotti fp ON bp.prodotto_id = fp.id
        WHERE b.fornitore_id = ? AND b.data >= ?
        GROUP BY prodotto_id
    """
    consumi_7g_raw = db.execute(consumi_7g_query, (id, sette_giorni_fa)).fetchall()
    consumi_7g_dict = {row['prodotto_id']: row['quantita_7g'] for row in consumi_7g_raw}

    consumi_per_prodotto = {}
    for c in consumi_raw:
        prod_id = c['prodotto_id']
        prod_nome = c['prodotto']
        if prod_nome not in consumi_per_prodotto:
            consumi_per_prodotto[prod_nome] = {
                'id': prod_id,
                'mesi': [],
                'ultimi_7g': consumi_7g_dict.get(prod_id, 0)
            }
        consumi_per_prodotto[prod_nome]['mesi'].append({'mese': c['mese'], 'quantita': c['totale_quantita']})

    stats = {
        'totale_assoluto': totale_assoluto,
        'spesa_mese_corrente': spesa_mese_corrente,
        'variazione_perc': variazione_perc,
        'storico_mesi': storico_mesi_sorted
    }

    return render_template('fornitore_detail.html',
                           fornitore=fornitore,
                           prodotti=prodotti,
                           bolle=bolle_with_totals,
                           stats=stats,
                           consumi=consumi_per_prodotto)

@app.route('/catalogo/<int:id>/modifica', methods=['POST'])
def catalogo_modifica(id):
    db = get_db()
    fornitore_id = request.form.get('fornitore_id')

    codice_ricambio = request.form.get('codice_ricambio')
    nome_ricambio = request.form.get('nome_ricambio')
    marchio = request.form.get('marchio')
    modello_auto = request.form.get('modello_auto')
    anno = request.form.get('anno')
    ultimo_prezzo = request.form.get('ultimo_prezzo') or 0.0

    db.execute('''
        UPDATE catalogo_ricambi
        SET codice_ricambio = ?, nome_ricambio = ?, marchio = ?, modello_auto = ?, anno = ?, ultimo_prezzo = ?
        WHERE id = ?
    ''', (codice_ricambio, nome_ricambio, marchio, modello_auto, anno, ultimo_prezzo, id))
    db.commit()

    if fornitore_id:
        return redirect(url_for('fornitore_detail', id=fornitore_id) + '#catalogo')
    return redirect(url_for('fornitori_list'))


@app.route('/catalogo/<int:id>/elimina', methods=['POST'])
def catalogo_elimina(id):
    db = get_db()
    fornitore_id = request.form.get('fornitore_id')
    db.execute('DELETE FROM catalogo_ricambi WHERE id = ?', (id,))
    db.commit()

    if fornitore_id:
        return redirect(url_for('fornitore_detail', id=fornitore_id) + '#catalogo')
    return redirect(url_for('fornitori_list'))


@app.route('/api/ricerca_catalogo', methods=['GET'])
def api_ricerca_catalogo():
    db = get_db()
    marchio = request.args.get('marchio', '')
    modello = request.args.get('modello', '')
    nome_ricambio = request.args.get('nome_ricambio', '')

    query = "SELECT * FROM catalogo_ricambi WHERE 1=1"
    params = []

    if marchio:
        query += " AND marchio LIKE ?"
        params.append(f"%{marchio}%")
    if modello:
        query += " AND modello_auto LIKE ?"
        params.append(f"%{modello}%")
    if nome_ricambio:
        query += " AND nome_ricambio LIKE ?"
        params.append(f"%{nome_ricambio}%")

    query += " ORDER BY nome_ricambio ASC, marchio ASC"

    rows = db.execute(query, params).fetchall()

    risultati = []
    for r in rows:
        risultati.append({
            'id': r['id'],
            'codice_ricambio': r['codice_ricambio'] or '',
            'nome_ricambio': r['nome_ricambio'],
            'marchio': r['marchio'] or '',
            'modello_auto': r['modello_auto'] or '',
            'anno': r['anno'] or '',
            'ultimo_prezzo': r['ultimo_prezzo'] or 0.0
        })

    return jsonify({'risultati': risultati})

@app.route('/api/fornitore/<int:fornitore_id>/prodotto/<int:prodotto_id>/consumi')
def api_consumi_prodotto(fornitore_id, prodotto_id):
    db = get_db()

    # Raggruppa consumi per settimana (anno-settimana)
    query = """
        SELECT strftime('%Y-%W', b.data) as settimana, MIN(b.data) as data_inizio_settimana, SUM(bp.quantita) as quantita
        FROM bolla_prodotti bp
        JOIN bolle b ON bp.bolla_id = b.id
        WHERE b.fornitore_id = ? AND bp.prodotto_id = ? AND b.data IS NOT NULL
        GROUP BY settimana
        ORDER BY b.data ASC
    """

    rows = db.execute(query, (fornitore_id, prodotto_id)).fetchall()

    labels = []
    data = []

    for r in rows:
        labels.append(r['data_inizio_settimana']) # Usiamo la data come label
        data.append(r['quantita'])

    return jsonify({
        'labels': labels,
        'data': data
    })

@app.route('/fornitore/<int:id>/prodotto/nuovo', methods=['POST'])
def fornitore_prodotto_nuovo(id):
    db = get_db()
    nome = request.form.get('nome')
    prezzo = float(request.form.get('prezzo_listino') or 0.0)
    db.execute('INSERT INTO fornitore_prodotti (fornitore_id, nome, prezzo_listino) VALUES (?, ?, ?)', (id, nome, prezzo))
    db.commit()
    return redirect(url_for('fornitore_detail', id=id) + '#prodotti')

import pandas as pd
from io import BytesIO

@app.route('/fornitore/<int:id>/export')
def fornitore_export(id):
    db = get_db()
    fornitore = db.execute('SELECT nome FROM fornitori WHERE id = ?', (id,)).fetchone()
    if not fornitore:
        return "Fornitore non trovato", 404

    export_type = request.args.get('type', 'all') # all, month, year, custom
    export_format = request.args.get('format', 'excel') # excel or pdf

    query = """
        SELECT b.data as 'Data Bolla', b.codice as 'Codice Bolla',
               COALESCE(fp.nome, bp.nome_ricambio) as 'Prodotto', bp.quantita as 'Quantità',
               bp.prezzo_applicato as 'Prezzo Unitario (€)',
               (bp.quantita * bp.prezzo_applicato * (1 - COALESCE(bp.sconto_perc, 0) / 100.0)) as 'Totale Riga (€)',
               b.note as 'Note Bolla'
        FROM bolle b
        LEFT JOIN bolla_prodotti bp ON b.id = bp.bolla_id
        LEFT JOIN fornitore_prodotti fp ON bp.prodotto_id = fp.id
        WHERE b.fornitore_id = ?
    """
    params = [id]

    now = datetime.now()
    if export_type == 'current_month':
        query += " AND strftime('%Y-%m', b.data) = ?"
        params.append(now.strftime('%Y-%m'))
    elif export_type == 'current_year':
        query += " AND strftime('%Y', b.data) = ?"
        params.append(now.strftime('%Y'))
    elif export_type == 'specific_month':
        month_val = request.args.get('month_val') # format YYYY-MM
        if month_val:
            query += " AND strftime('%Y-%m', b.data) = ?"
            params.append(month_val)
    elif export_type == 'specific_year':
        year_val = request.args.get('year_val') # format YYYY
        if year_val:
            query += " AND strftime('%Y', b.data) = ?"
            params.append(year_val)
    elif export_type == 'custom_range':
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        if date_from and date_to:
            query += " AND b.data BETWEEN ? AND ?"
            params.extend([date_from, date_to])

    query += " ORDER BY b.data DESC, b.id DESC"

    rows = db.execute(query, params).fetchall()

    # Export PDF logic
    if export_format == 'pdf':
        total_sum = sum((r['Totale Riga (€)'] or 0.0) for r in rows) if rows else 0.0

        # Determine the subtitle based on filters
        periodo_filtro = "Tutto lo storico"
        if export_type == 'current_month':
            periodo_filtro = f"Mese: {now.strftime('%Y-%m')}"
        elif export_type == 'current_year':
            periodo_filtro = f"Anno: {now.strftime('%Y')}"
        elif export_type == 'specific_month':
            periodo_filtro = f"Mese: {request.args.get('month_val')}"
        elif export_type == 'specific_year':
            periodo_filtro = f"Anno: {request.args.get('year_val')}"
        elif export_type == 'custom_range':
            periodo_filtro = f"Dal {request.args.get('date_from')} al {request.args.get('date_to')}"

        html_content = render_template('template_pdf_bolle.html',
                                       fornitore=fornitore['nome'],
                                       data_odierna=now.strftime('%d/%m/%Y'),
                                       periodo=periodo_filtro,
                                       righe=rows,
                                       totale=total_sum)

        options = {
            'page-size': 'A4',
            'margin-top': '0.5cm',
            'margin-right': '0.5cm',
            'margin-bottom': '0.5cm',
            'margin-left': '0.5cm',
            'encoding': "UTF-8",
            'print-media-type': None,
            'enable-local-file-access': None
        }

        # Setup paths as we did for vehicle PDFs
        root_path = app.root_path
        file_url_prefix = f"file:///{root_path.replace(os.sep, '/').lstrip('/')}/static/"
        html_content = html_content.replace('src="/static/', f'src="{file_url_prefix}')

        wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
        config = None
        if os.path.exists(wkhtmltopdf_path):
            config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

        try:
            pdf_bytes = pdfkit.from_string(html_content, False, options=options, configuration=config)
            filename = f"Export_{fornitore['nome'].replace(' ', '_')}_{now.strftime('%Y%m%d')}.pdf"
            return Response(pdf_bytes, mimetype='application/pdf', headers={"Content-disposition": f"attachment; filename={filename}"})
        except Exception as e:
            return f"Errore generazione PDF: {str(e)}", 500

    # Fallback to Excel export logic
    else:
        # Se non ci sono dati
        if not rows:
            df = pd.DataFrame(columns=['Nessun dato trovato per i criteri selezionati'])
        else:
            df = pd.DataFrame([dict(row) for row in rows])

            # Aggiungi riga totale in fondo
            if 'Totale Riga (€)' in df.columns:
                total_sum = df['Totale Riga (€)'].sum()
                total_row = pd.DataFrame([{
                    'Data Bolla': 'TOTALE GLOBALE',
                    'Codice Bolla': '',
                    'Prodotto': '',
                    'Quantità': '',
                    'Prezzo Unitario (€)': '',
                    'Totale Riga (€)': total_sum,
                    'Note Bolla': ''
                }])
                df = pd.concat([df, total_row], ignore_index=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Bolle')

        output.seek(0)

        filename = f"Export_{fornitore['nome'].replace(' ', '_')}_{now.strftime('%Y%m%d')}.xlsx"

        return Response(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )

@app.route('/fornitore/<int:id>/elimina', methods=['POST'])
def fornitore_elimina(id):
    db = get_db()
    # Delete cascaded data
    bolle = db.execute('SELECT id FROM bolle WHERE fornitore_id = ?', (id,)).fetchall()
    for b in bolle:
        db.execute('DELETE FROM bolla_prodotti WHERE bolla_id = ?', (b['id'],))
    db.execute('DELETE FROM bolle WHERE fornitore_id = ?', (id,))
    db.execute('DELETE FROM fornitore_prodotti WHERE fornitore_id = ?', (id,))
    db.execute('DELETE FROM fornitori WHERE id = ?', (id,))
    db.commit()
    return redirect(url_for('fornitori_list'))

@app.route('/bolla/nuova', methods=['POST'])
def bolla_nuova():
    db = get_db()
    fornitore_id = request.form.get('fornitore_id')
    codice = request.form.get('codice')
    data = request.form.get('data') or datetime.now().strftime('%Y-%m-%d')
    note = request.form.get('note')

    # Se il fornitore appartiene alla categoria 'Varie' e non c'è un codice reale
    fornitore = db.execute('SELECT categoria FROM fornitori WHERE id = ?', (fornitore_id,)).fetchone()
    if fornitore and fornitore['categoria'] == 'Varie':
        if not codice or codice == 'SPESA':
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            codice = f"SPESA-{timestamp}"

    cursor = db.execute('INSERT INTO bolle (fornitore_id, codice, data, note) VALUES (?, ?, ?, ?)', (fornitore_id, codice, data, note))
    db.commit()
    return redirect(url_for('bolla_detail', id=cursor.lastrowid))

@app.route('/bolla/<int:id>', methods=['GET', 'POST'])
def bolla_detail(id):
    db = get_db()
    if request.method == 'POST':
        # Update bolla
        codice = request.form.get('codice')
        data = request.form.get('data')
        note = request.form.get('note')
        db.execute('UPDATE bolle SET codice=?, data=?, note=? WHERE id=?', (codice, data, note, id))
        db.commit()
        return redirect(url_for('bolla_detail', id=id))

    bolla = db.execute('SELECT b.*, f.nome as fornitore_nome, f.categoria as fornitore_categoria FROM bolle b JOIN fornitori f ON b.fornitore_id = f.id WHERE b.id = ?', (id,)).fetchone()
    if not bolla:
        return redirect(url_for('fornitori_list'))

    righe = db.execute('''
        SELECT bp.*, COALESCE(fp.nome, bp.nome_ricambio) as nome
        FROM bolla_prodotti bp
        LEFT JOIN fornitore_prodotti fp ON bp.prodotto_id = fp.id
        WHERE bp.bolla_id = ?
    ''', (id,)).fetchall()

    prodotti_fornitore = db.execute('SELECT * FROM fornitore_prodotti WHERE fornitore_id = ? ORDER BY nome', (bolla['fornitore_id'],)).fetchall()
    veicoli_attivi = db.execute("SELECT id, targa, marca, modello, anno FROM veicoli WHERE riconsegnata = 0 ORDER BY targa ASC").fetchall()

    return render_template('bolla_detail.html', bolla=bolla, righe=righe, prodotti_fornitore=prodotti_fornitore, veicoli_attivi=veicoli_attivi)

@app.route('/bolla/<int:id>/prodotto/nuovo', methods=['POST'])
def bolla_prodotto_nuovo(id):
    db = get_db()
    bolla = db.execute('SELECT b.*, f.categoria as fornitore_categoria FROM bolle b JOIN fornitori f ON b.fornitore_id = f.id WHERE b.id = ?', (id,)).fetchone()
    if not bolla:
        return redirect(url_for('fornitori_list'))

    quantita = int(request.form.get('quantita') or 1)
    custom_nome = request.form.get('custom_nome')
    sconto_perc = float(request.form.get('sconto_perc') or 0.0)

    if bolla['fornitore_categoria'] == 'Ricambi':
        # Logica per Ricambi
        codice_ricambio = request.form.get('codice_ricambio')
        marchio = request.form.get('marchio')
        modello_auto = request.form.get('modello_auto')
        anno = request.form.get('anno')
        custom_prezzo = float(request.form.get('custom_prezzo') or 0.0)

        veicolo_targa = request.form.get('veicolo_targa') or None
        stato_ordine = 'ORDINATO'
        stato_consegna = 'IN OFFICINA'

        # 1. Salva la riga nella bolla
        cursor = db.execute('''
            INSERT INTO bolla_prodotti
            (bolla_id, quantita, prezzo_applicato, sconto_perc, nome_ricambio, codice_ricambio, marchio, modello_auto, anno, veicolo_targa, stato_ordine, stato_consegna)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (id, quantita, custom_prezzo, sconto_perc, custom_nome, codice_ricambio, marchio, modello_auto, anno, veicolo_targa, stato_ordine, stato_consegna))

        new_bolla_prodotto_id = cursor.lastrowid

        # 2. Upsert nel catalogo dinamico
        if codice_ricambio:
            existing = db.execute('SELECT id FROM catalogo_ricambi WHERE codice_ricambio = ?', (codice_ricambio,)).fetchone()
        else:
            existing = db.execute('SELECT id FROM catalogo_ricambi WHERE nome_ricambio = ? AND marchio = ? AND modello_auto = ?',
                                  (custom_nome, marchio or '', modello_auto or '')).fetchone()

        if existing:
            db.execute('UPDATE catalogo_ricambi SET ultimo_prezzo = ? WHERE id = ?', (custom_prezzo, existing['id']))
        else:
            db.execute('''
                INSERT INTO catalogo_ricambi (codice_ricambio, nome_ricambio, marchio, modello_auto, anno, ultimo_prezzo)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (codice_ricambio, custom_nome, marchio, modello_auto, anno, custom_prezzo))

        # 3. Copia carbone nella scheda veicolo
        if veicolo_targa:
            veicolo = db.execute('SELECT id FROM veicoli WHERE targa = ?', (veicolo_targa,)).fetchone()
            if veicolo:
                veicolo_id = veicolo['id']
                prezzo_scontato = custom_prezzo * (1 - (sconto_perc or 0) / 100.0)
                totale_ricambio = prezzo_scontato * quantita

                # Inseriamo il ricambio specificando che è già ordinato e in carrozzeria (in officina)
                db.execute('''
                    INSERT INTO ricambi (veicolo_id, nome, prezzo, ordinato, in_carrozzeria, bolla_prodotto_id)
                    VALUES (?, ?, ?, 1, 1, ?)
                ''', (veicolo_id, custom_nome, totale_ricambio, new_bolla_prodotto_id))

        db.commit()
    else:
        # Logica standard per Materiale e Varie
        prodotto_id = request.form.get('prodotto_id')
        custom_prezzo = float(request.form.get('custom_prezzo') or 0.0)

        if not prodotto_id and custom_nome:
            # Create a new product in the fornitore's listino first
            cursor = db.execute('INSERT INTO fornitore_prodotti (fornitore_id, nome, prezzo_listino) VALUES (?, ?, ?)', (bolla['fornitore_id'], custom_nome, custom_prezzo))
            prodotto_id = cursor.lastrowid
            prezzo_applicato = custom_prezzo
        else:
            # Fetch standard price if not overridden
            prezzo_applicato = request.form.get('prezzo_applicato')
            if not prezzo_applicato:
                prod = db.execute('SELECT prezzo_listino FROM fornitore_prodotti WHERE id = ?', (prodotto_id,)).fetchone()
                prezzo_applicato = prod['prezzo_listino'] if prod else 0.0
            else:
                prezzo_applicato = float(prezzo_applicato)

        if prodotto_id:
            db.execute('INSERT INTO bolla_prodotti (bolla_id, prodotto_id, quantita, prezzo_applicato, sconto_perc) VALUES (?, ?, ?, ?, ?)', (id, prodotto_id, quantita, prezzo_applicato, sconto_perc))
            db.commit()

    return redirect(url_for('bolla_detail', id=id))

@app.route('/bolla/<int:id>/elimina', methods=['POST'])
def bolla_elimina(id):
    db = get_db()
    bolla = db.execute('SELECT fornitore_id FROM bolle WHERE id = ?', (id,)).fetchone()
    if bolla:
        db.execute('DELETE FROM bolla_prodotti WHERE bolla_id = ?', (id,))
        db.execute('DELETE FROM bolle WHERE id = ?', (id,))
        db.commit()
        return redirect(url_for('fornitore_detail', id=bolla['fornitore_id']))
    return redirect(url_for('fornitori_list'))

@app.route("/prodotto/<int:id>/modifica", methods=["GET", "POST"])
def prodotto_modifica(id):
    db = get_db()
    if request.method == "POST":
        nome = request.form.get("nome")
        prezzo_listino = request.form.get("prezzo_listino") or 0.0
        db.execute("UPDATE fornitore_prodotti SET nome = ?, prezzo_listino = ? WHERE id = ?", (nome, prezzo_listino, id))
        db.commit()
        prod = db.execute("SELECT fornitore_id FROM fornitore_prodotti WHERE id = ?", (id,)).fetchone()
        if prod:
            return redirect(url_for("fornitore_detail", id=prod["fornitore_id"]))
        return redirect(url_for("fornitori_list"))
    prodotto = db.execute("SELECT * FROM fornitore_prodotti WHERE id = ?", (id,)).fetchone()
    if not prodotto:
        return redirect(url_for("fornitori_list"))
    fornitore = db.execute("SELECT * FROM fornitori WHERE id = ?", (prodotto["fornitore_id"],)).fetchone()
    return render_template("prodotto_edit.html", prodotto=prodotto, fornitore=fornitore)

@app.route("/bolla/riga/<int:id>/modifica", methods=["GET", "POST"])
def bolla_riga_modifica(id):
    db = get_db()
    if request.method == "POST":
        quantita = request.form.get("quantita") or 1
        prezzo_applicato = request.form.get("prezzo_applicato") or 0.0
        sconto_perc = request.form.get("sconto_perc") or 0.0

        # Check if the request contains fields specific to 'Ricambi'
        nome_ricambio = request.form.get("nome_ricambio")
        if nome_ricambio is not None: # Means it's a Ricambi form
            codice_ricambio = request.form.get("codice_ricambio")
            marchio = request.form.get("marchio")
            modello_auto = request.form.get("modello_auto")
            anno = request.form.get("anno")
            veicolo_targa_new = request.form.get("veicolo_targa") or None

            # Recupera la riga precedente per confrontare la targa
            riga_prec = db.execute("SELECT veicolo_targa FROM bolla_prodotti WHERE id = ?", (id,)).fetchone()
            veicolo_targa_old = riga_prec['veicolo_targa'] if riga_prec else None

            db.execute("""
                UPDATE bolla_prodotti
                SET quantita = ?, prezzo_applicato = ?, sconto_perc = ?,
                    nome_ricambio = ?, codice_ricambio = ?, marchio = ?, modello_auto = ?, anno = ?, veicolo_targa = ?
                WHERE id = ?
            """, (quantita, prezzo_applicato, sconto_perc, nome_ricambio, codice_ricambio, marchio, modello_auto, anno, veicolo_targa_new, id))

            # Gestione Copia Carbone
            if veicolo_targa_new != veicolo_targa_old:
                # 1. Se c'era una targa precedente, rimuovi la copia carbone dal veicolo vecchio
                if veicolo_targa_old:
                    veicolo_old = db.execute('SELECT id FROM veicoli WHERE targa = ?', (veicolo_targa_old,)).fetchone()
                    if veicolo_old:
                        db.execute('DELETE FROM ricambi WHERE veicolo_id = ? AND bolla_prodotto_id = ?', (veicolo_old['id'], id))

                # 2. Se c'è una nuova targa, inserisci la copia carbone nel nuovo veicolo
                if veicolo_targa_new:
                    veicolo_new = db.execute('SELECT id FROM veicoli WHERE targa = ?', (veicolo_targa_new,)).fetchone()
                    if veicolo_new:
                        prezzo_scontato = float(prezzo_applicato) * (1 - float(sconto_perc) / 100.0)
                        totale_ricambio = prezzo_scontato * float(quantita)

                        db.execute('''
                            INSERT INTO ricambi (veicolo_id, nome, prezzo, ordinato, in_carrozzeria, bolla_prodotto_id)
                            VALUES (?, ?, ?, 1, 1, ?)
                        ''', (veicolo_new['id'], nome_ricambio, totale_ricambio, id))

        else:
            db.execute("UPDATE bolla_prodotti SET quantita = ?, prezzo_applicato = ?, sconto_perc = ? WHERE id = ?", (quantita, prezzo_applicato, sconto_perc, id))

        db.commit()
        riga = db.execute("SELECT bolla_id FROM bolla_prodotti WHERE id = ?", (id,)).fetchone()
        if riga:
            return redirect(url_for("bolla_detail", id=riga["bolla_id"]))
        return redirect(url_for("fornitori_list"))
    riga = db.execute("""
        SELECT bp.*, COALESCE(fp.nome, bp.nome_ricambio) as nome, f.categoria as fornitore_categoria
        FROM bolla_prodotti bp
        LEFT JOIN fornitore_prodotti fp ON bp.prodotto_id = fp.id
        JOIN bolle b ON bp.bolla_id = b.id
        JOIN fornitori f ON b.fornitore_id = f.id
        WHERE bp.id = ?
    """, (id,)).fetchone()
    if not riga:
        return redirect(url_for("fornitori_list"))

    veicoli = []
    if riga['fornitore_categoria'] == 'Ricambi':
        veicoli = db.execute('SELECT id, targa, marca, modello, anno FROM veicoli ORDER BY targa').fetchall()

    return render_template("bolla_riga_edit.html", riga=riga, veicoli=veicoli)

@app.route('/bolla/riga/<int:id>/elimina', methods=['POST'])
def bolla_riga_elimina(id):
    db = get_db()
    riga = db.execute('SELECT bolla_id FROM bolla_prodotti WHERE id = ?', (id,)).fetchone()
    if riga:
        db.execute('DELETE FROM ricambi WHERE bolla_prodotto_id = ?', (id,))
        db.execute('DELETE FROM bolla_prodotti WHERE id = ?', (id,))
        db.commit()
        return redirect(url_for('bolla_detail', id=riga['bolla_id']))
    return redirect(url_for('fornitori_list'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)