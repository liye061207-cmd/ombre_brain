import http.server
import sqlite3
import json
import os
import glob
import yaml
import asyncio
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from portrait_engine import DailyPortraitMaintainer as PortraitEngine
    HAS_PORTRAIT_ENGINE = True
except Exception:
    HAS_PORTRAIT_ENGINE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'state', 'persona_state.db')
BUCKETS_DIR = os.path.join(BASE_DIR, 'buckets')
GATEWAY_LOG = os.path.join(BASE_DIR, 'gateway.log')
HTML_PATH = os.path.join(BASE_DIR, 'dashboard.html')

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/mood':
            self._serve_mood()
        elif self.path == '/api/memory':
            self._serve_memory()
        elif self.path == '/api/recall':
            self._serve_recall()
        elif self.path == '/api/portrait':
            self._serve_portrait()
        elif self.path == '/api/portrait/generate':
            self._serve_portrait_generate()
        elif self.path == '/api/dreams':
            self._serve_dreams()
        elif self.path == '/api/system':
            self._serve_system()
        elif self.path == '/api/extract':
            self._serve_extract()
        elif self.path == '/manifest.json':
            self._serve_static('manifest.json', 'application/json')
        elif self.path == '/sw.js':
            self._serve_static('sw.js', 'application/javascript')
        elif self.path == '/icon-192.png' or self.path == '/icon-512.png':
            self._serve_icon()
        elif self.path == '/' or self.path == '/dashboard':
            self._serve_html()
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _serve_mood(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute('SELECT * FROM persona_session_state ORDER BY updated_at DESC LIMIT 1').fetchone()
            conn.close()
            if row:
                data = {
                    'valence': row[2], 'arousal': row[3], 'tenderness': row[4],
                    'possessiveness': row[5], 'longing': row[6], 'security': row[7],
                    'protective_drive': row[8], 'libido': row[9], 'mood_label': row[10],
                    'inner_thought': row[13] or '', 'updated_at': (row[14] or '')[:19].replace('T', ' ')
                }
            else:
                data = {'error': 'no data'}
            self._json(data)
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_memory(self):
        try:
            total = 0
            types = {}
            domains = {}
            recent = []
            archive_count = 0
            for root, dirs, files in os.walk(BUCKETS_DIR):
                if '_app' in root:
                    continue
                is_archive = 'archive' in root
                for f in files:
                    if not f.endswith('.md'):
                        continue
                    if is_archive:
                        archive_count += 1
                        continue
                    total += 1
                    path = os.path.join(root, f)
                    try:
                        with open(path) as fh:
                            content = fh.read()
                        if content.startswith('---'):
                            parts = content.split('---', 2)
                            if len(parts) >= 3:
                                meta = yaml.safe_load(parts[1])
                                if meta:
                                    t = meta.get('type', 'unknown')
                                    types[t] = types.get(t, 0) + 1
                                    d = meta.get('domain', '')
                                    if isinstance(d, list):
                                        for dd in d:
                                            domains[dd] = domains.get(dd, 0) + 1
                                    elif d:
                                        domains[d] = domains.get(d, 0) + 1
                                    recent.append({
                                        'name': meta.get('name', f)[:60],
                                        'importance': meta.get('importance', 0),
                                        'type': t,
                                        'updated': str(meta.get('updated_at', ''))[:19]
                                    })
                    except:
                        pass
            recent.sort(key=lambda x: x.get('updated', ''), reverse=True)
            self._json({
                'total': total,
                'archive': archive_count,
                'types': types,
                'domains': dict(sorted(domains.items(), key=lambda x: x[1], reverse=True)[:10]),
                'recent': recent[:10]
            })
        except Exception as e:
            self._json({'error': str(e)})

    def _load_id_map(self):
        id_map = {}
        for root, dirs, files in os.walk(BUCKETS_DIR):
            if '_app' in root:
                continue
            for f in files:
                if not f.endswith('.md'):
                    continue
                path = os.path.join(root, f)
                try:
                    with open(path) as fh:
                        content = fh.read()
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            meta = yaml.safe_load(parts[1])
                            if meta and meta.get('id'):
                                id_map[meta['id']] = meta.get('name', f)[:60]
                except:
                    pass
        return id_map

    def _serve_recall(self):
        try:
            id_map = self._load_id_map()
            recalls = []
            if os.path.exists(GATEWAY_LOG):
                with open(GATEWAY_LOG) as f:
                    for line in f:
                        if 'recalled=' in line and 'round completed' in line:
                            try:
                                import re
                                match = re.search(r'recalled=\[(.*?)\]', line)
                                if match:
                                    ids_str = match.group(1).strip()
                                    if ids_str:
                                        ids = [i.strip().strip("'\"") for i in ids_str.split(',')]
                                        names = [id_map.get(i, i[:12]) for i in ids]
                                        recalls.append({
                                            'count': len(ids),
                                            'names': names,
                                            'time': line[:19]
                                        })
                                    else:
                                        recalls.append({'count': 0, 'names': [], 'time': line[:19]})
                            except:
                                pass
            self._json({'recent': recalls[-10:]})
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_portrait(self):
        try:
            portrait_path = os.path.join(BASE_DIR, 'state', 'portrait_state.json')
            if os.path.exists(portrait_path):
                with open(portrait_path) as f:
                    data = json.load(f)
                portrait = data.get('portrait', {})
                user = portrait.get('user', {})
                relationship = portrait.get('relationship', {})
                self._json({
                    'user_portrait': user.get('stable', '')[:500],
                    'relationship_portrait': relationship.get('stable', '')[:500],
                    'current_focus': user.get('mid_term', '')[:200],
                    'updated': str(data.get('updated_at', ''))[:19]
                })
            else:
                self._json({'error': '画像尚未生成，需在 Dashboard 中手动触发首次生成'})
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_portrait_generate(self):
        if not HAS_PORTRAIT_ENGINE:
            self._json({'error': 'portrait_engine 模块不可用'})
            return
        try:
            config_path = os.path.join(BASE_DIR, 'config.yaml')
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            portrait_cfg = cfg.get('portrait', {})
            engine = PortraitEngine(portrait_cfg)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(engine.maintain_daily(None, force=True))
            loop.close()
            self._json({'status': result.get('status', 'unknown'), 'detail': str(result)})
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_dreams(self):
        try:
            dreams_dir = os.path.join(BASE_DIR, 'state', 'dreams')
            if not os.path.exists(dreams_dir):
                self._json({'dreams': [], 'latest': None})
                return
            dream_files = sorted(
                glob.glob(os.path.join(dreams_dir, 'dream_*.md')),
                reverse=True
            )
            dreams = []
            for f in dream_files:
                try:
                    with open(f) as fh:
                        content = fh.read()
                    meta = {}
                    body = content
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            meta = yaml.safe_load(parts[1]) or {}
                            body = parts[2].strip()
                    dreams.append({
                        'id': meta.get('dream_id', os.path.basename(f)),
                        'date': meta.get('local_date', ''),
                        'generated_at': str(meta.get('generated_at', ''))[:19],
                        'core_affect': meta.get('core_affect', {}),
                        'recall_cues': meta.get('recall_cues', []),
                        'surfaced': meta.get('surfaced', False),
                        'body': body[:2000]
                    })
                except:
                    pass
            self._json({
                'dreams': dreams,
                'latest': dreams[0] if dreams else None
            })
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_static(self, filename, content_type):
        try:
            filepath = os.path.join(BASE_DIR, filename)
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            self.wfile.write(content)
        except:
            self.send_response(404)
            self.end_headers()

    def _serve_icon(self):
        try:
            size = 192 if '192' in self.path else 512
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 {s} {s}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1a1040"/>
      <stop offset="100%" style="stop-color:#0a0a18"/>
    </linearGradient>
    <linearGradient id="glow" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#a78bfa"/>
      <stop offset="100%" style="stop-color:#7c6af0"/>
    </linearGradient>
    <filter id="blur">
      <feGaussianBlur stdDeviation="{b}"/>
    </filter>
  </defs>
  <rect width="{s}" height="{s}" rx="{r}" fill="url(#bg)"/>
  <circle cx="{s2}" cy="{s2}" r="{r2}" fill="url(#glow)" opacity="0.3" filter="url(#blur)"/>
  <circle cx="{s2}" cy="{s2}" r="{r3}" fill="none" stroke="url(#glow)" stroke-width="{sw}" opacity="0.6"/>
  <text x="{s2}" y="{ty}" text-anchor="middle" fill="#c8b8f0" font-family="sans-serif" font-weight="300" font-size="{fs}" letter-spacing="4">OMBRE</text>
</svg>'''.format(
                s=size, b=size*0.08, r=size*0.22, s2=size//2,
                r2=size*0.3, r3=size*0.25, sw=size*0.015,
                ty=size*0.56, fs=size*0.12
            )
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(svg.encode())
        except:
            self.send_response(404)
            self.end_headers()

    def _serve_system(self):
        try:
            import subprocess
            # PM2 状态
            pm2 = subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, timeout=5)
            processes = []
            if pm2.returncode == 0:
                import json as _json
                plist = _json.loads(pm2.stdout)
                for p in plist:
                    processes.append({
                        'name': p.get('name',''),
                        'status': p.get('pm2_env',{}).get('status','unknown'),
                        'cpu': p.get('monit',{}).get('cpu',0),
                        'memory': p.get('monit',{}).get('memory',0)
                    })
            # 系统资源
            mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=3)
            mem_lines = mem.stdout.strip().split('\n')
            mem_total = mem_used = 0
            if len(mem_lines) > 1:
                parts = mem_lines[1].split()
                if len(parts) >= 3:
                    mem_total = int(parts[1])
                    mem_used = int(parts[2])
            disk = subprocess.run(['df', '-m', '/'], capture_output=True, text=True, timeout=3)
            disk_lines = disk.stdout.strip().split('\n')
            disk_total = disk_used = 0
            if len(disk_lines) > 1:
                parts = disk_lines[1].split()
                if len(parts) >= 3:
                    disk_total = int(parts[1])
                    disk_used = int(parts[2])
            # 端口检查
            ports = {}
            for port in [18001, 18002, 18003, 8080, 8000]:
                r = subprocess.run(['ss', '-tlnp'], capture_output=True, text=True, timeout=3)
                ports[str(port)] = f':{port} ' in r.stdout
            self._json({
                'processes': processes,
                'memory': {'total': mem_total, 'used': mem_used, 'pct': round(mem_used/mem_total*100,1) if mem_total else 0},
                'disk': {'total': disk_total, 'used': disk_used, 'pct': round(disk_used/disk_total*100,1) if disk_total else 0},
                'ports': ports
            })
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_extract(self):
        try:
            import json as _json
            state_path = '/opt/Dylan-heartbeat/memory_extract_state.json'
            if os.path.exists(state_path):
                with open(state_path) as f:
                    state = _json.load(f)
                self._json({
                    'last_extract': state.get('lastExtractTime'),
                    'today_count': state.get('todayExtractCount', 0),
                    'extracted_ids': len(state.get('extractedMessageIds', [])),
                    'last_daily': state.get('lastDailyDate')
                })
            else:
                self._json({'error': 'state file not found'})
        except Exception as e:
            self._json({'error': str(e)})

    def _serve_html(self):
        try:
            with open(HTML_PATH, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content)
        except:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    os.chdir(BASE_DIR)
    server = http.server.HTTPServer(('0.0.0.0', 18003), DashboardHandler)
    print('Dashboard server running on :18003')
    server.serve_forever()
