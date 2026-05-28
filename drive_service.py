import os
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import datetime

SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_account.json'
# We will create a root folder named "Gestione Carrozzeria" if it doesn't exist
ROOT_FOLDER_NAME = "Gestione Carrozzeria"

import json
from google.oauth2.credentials import Credentials as OAuthCredentials

def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        # Prefer OAuth2 token if available to save exactly where the user expects
        creds = OAuthCredentials.from_authorized_user_file('token.json', SCOPES)
    elif os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    else:
        print("Warning: Neither token.json nor service_account.json found. Drive features will be disabled.")
        return None

    service = build('drive', 'v3', credentials=creds)
    return service

def get_or_create_root_folder(service):
    query = f"name = '{ROOT_FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    if not files:
        file_metadata = {
            'name': ROOT_FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    return files[0].get('id')

def get_or_create_temp_folder(service):
    root_id = get_or_create_root_folder(service)
    query = f"name = 'Temp_Officina' and '{root_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    if not files:
        file_metadata = {
            'name': 'Temp_Officina',
            'parents': [root_id],
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    return files[0].get('id')

def get_or_create_vehicle_folder(service, root_folder_id, folder_name):
    safe_folder_name = folder_name.replace("'", "\\'")
    query = f"name = '{safe_folder_name}' and '{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    if not files:
        file_metadata = {
            'name': folder_name,
            'parents': [root_folder_id],
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    return files[0].get('id')

def rename_folder(service, folder_id, new_name):
    file_metadata = {'name': new_name}
    service.files().update(fileId=folder_id, body=file_metadata).execute()

def rename_file(service, file_id, new_name):
    file_metadata = {'name': new_name}
    service.files().update(fileId=file_id, body=file_metadata).execute()

def upload_photo(service, folder_id, file_path, filename):
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    media = MediaIoBaseUpload(io.FileIO(file_path, 'rb'), mimetype='image/jpeg', resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

def list_photos(service, folder_id):
    # Retrieve only image files (exclude text/backup files like .txt)
    query = f"'{folder_id}' in parents and trashed = false and mimeType contains 'image/'"
    # Use webViewLink to open image in browser instead of forcing download (webContentLink)
    response = service.files().list(q=query, spaces='drive', fields='files(id, name, thumbnailLink, webViewLink)').execute()
    return response.get('files', [])

def delete_photo(service, file_id):
    service.files().delete(fileId=file_id).execute()

def download_file(service, file_id, dest_path):
    import io
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(dest_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()

def move_file(service, file_id, new_folder_id):
    # Retrieve the existing parents to remove
    file = service.files().get(fileId=file_id, fields='parents').execute()
    previous_parents = ",".join(file.get('parents'))

    # Move the file to the new folder
    file = service.files().update(
        fileId=file_id,
        addParents=new_folder_id,
        removeParents=previous_parents,
        fields='id, parents'
    ).execute()
    return file

def upload_vehicle_data_txt(service, folder_id, content, filename="dati_veicolo.txt"):
    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])

    media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype='text/plain', resumable=True)

    if files:
        file_id = files[0].get('id')
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        service.files().create(body=file_metadata, media_body=media).execute()

def upload_vehicle_pdf(service, folder_id, pdf_bytes, filename="preventivo.pdf"):
    try:
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = response.get('files', [])

        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)

        if files:
            file_id = files[0].get('id')
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"[Drive API] Sovrascritto PDF esistente: {filename}")
        else:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print(f"[Drive API] Caricato nuovo PDF: {filename}")
    except Exception as e:
        print(f"Errore Drive API: {e}")
# Background text file update
def update_veicoli_txt(service, root_folder_id, db_path='officina.db'):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    veicoli = conn.execute('SELECT * FROM veicoli').fetchall()

    # Format rows like the old bot: Targa | Nome | Stato | Note | Telefono | Data Arrivo | Data Cons | Data Prev
    lines = []
    for v in veicoli:
        nome_display = f"{v['marca'] or ''} {v['modello'] or ''}".strip()
        if not nome_display:
            nome_display = "Veicolo Sconosciuto"

        # We need a client query for prop and tel
        prop = "ND"
        tel = "ND"
        if v['cliente_id']:
            cliente = conn.execute('SELECT nome, telefono FROM clienti WHERE id=?', (v['cliente_id'],)).fetchone()
            if cliente:
                prop = cliente['nome']
                tel = cliente['telefono'] or "ND"

        line = f"{v['targa']} | {nome_display} | {v['stato']} | {prop} | {tel} | {v['data_arrivo'] or 'ND'} | {v['data_consegna_prevista'] or 'DA DEFINIRE'} | ND"
        lines.append(line.upper())

    content = "\n".join(lines)

    # Find existing file
    query = f"name = 'Veicoli_DB.txt' and '{root_folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])

    media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype='text/plain', resumable=True)

    if files:
        file_id = files[0].get('id')
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {
            'name': 'Veicoli_DB.txt',
            'parents': [root_folder_id]
        }
        service.files().create(body=file_metadata, media_body=media).execute()

def update_fornitori_txt(service, root_folder_id, db_path='officina.db'):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    fornitori = conn.execute('SELECT * FROM fornitori').fetchall()

    lines = ["*** REGISTRO FORNITORI E BOLLE ***\n"]

    for f in fornitori:
        lines.append(f"FORNITORE: {f['nome']} | TEL: {f['telefono'] or 'ND'} | NOTE: {f['note'] or 'ND'}".upper())

        bolle = conn.execute('SELECT * FROM bolle WHERE fornitore_id = ? ORDER BY data DESC', (f['id'],)).fetchall()
        if not bolle:
            lines.append("  Nessuna bolla registrata.\n")
            continue

        for b in bolle:
            totale_bolla = 0.0
            prodotti = conn.execute('''
                SELECT bp.quantita, bp.prezzo_applicato, bp.sconto_perc, COALESCE(fp.nome, bp.nome_ricambio) as nome
                FROM bolla_prodotti bp
                LEFT JOIN fornitore_prodotti fp ON bp.prodotto_id = fp.id
                WHERE bp.bolla_id = ?
            ''', (b['id'],)).fetchall()

            lines.append(f"  > BOLLA: {b['codice']} | DATA: {b['data']}".upper())
            for p in prodotti:
                tot_riga = p['quantita'] * p['prezzo_applicato'] * (1 - (p['sconto_perc'] or 0) / 100.0)
                totale_bolla += tot_riga
                lines.append(f"      - {p['quantita']}x {p['nome'].upper()} (cad. €{p['prezzo_applicato']:.2f}" + (f" - SC. {p['sconto_perc']}%" if p['sconto_perc'] else "") + f") = €{tot_riga:.2f}")
            lines.append(f"    TOTALE BOLLA: €{totale_bolla:.2f}\n")

        lines.append("-" * 40 + "\n")

    content = "\n".join(lines)

    query = f"name = 'Bolle_Fornitori.txt' and '{root_folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])

    media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype='text/plain', resumable=True)

    if files:
        file_id = files[0].get('id')
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {
            'name': 'Bolle_Fornitori.txt',
            'parents': [root_folder_id]
        }
        service.files().create(body=file_metadata, media_body=media).execute()