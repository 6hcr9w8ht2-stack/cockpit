#!/usr/bin/env python3
"""Build cockpit-v12 for GitHub Pages — multi-source: xuangubao, Tencent, AKShare, EastMoney."""
import json, os, sys, datetime, gzip
from urllib.request import Request, urlopen

BJT = datetime.timezone(datetime.timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = [
    ("000001","sh","上证指数"),("399001","sz","深证成指"),("399006","sz","创业板指"),
    ("000688","sh","科创50"),
]

def log(msg): print("  " + msg, flush=True)

def http_get(url, gbk=False, t=15):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Encoding": "gzip, deflate",
    })
    resp = urlopen(req, timeout=t)
    data = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    return data.decode("gbk" if gbk else "utf-8", errors="replace")

# 1. Library
print("1. Library...")
with open(os.path.join(BASE, 'lwcharts.js'), 'r', encoding='utf-8') as f:
    library = f.read()
library = library.replace('</script>', '<\\u002fscript>')
library = library.replace('</SCRIPT>', '<\\u002fSCRIPT>')
log(str(len(library)) + " chars")

# 2. K-line
print("2. K-line...")
kl_all = {}
for per in ['15','30','60','240','1200']:
    path = os.path.join(BASE, "_kl_" + per + ".json")
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        for code in data:
            if code not in kl_all: kl_all[code] = {}
            kl_all[code][per] = data[code]
    bc = sum(len(kl_all.get(c,{}).get(per,[])) for c in kl_all)
    log(per + ": " + str(bc) + " bars")

# 3. Macro
print("3. Macro...")
macro = {"cpi":[],"ppi":[],"pmi_mfg":[],"pmi_non_mfg":[],"social_retail":[],"margin":[],"northbound":[],
         "volume_trend":[],"etf":[],"bond_spread":[],"commodity":[],"shibor":[],"lpr":[],"bond10y":[],"m2":[]}

mp12 = os.path.join(BASE, '_macro_v12.json')
if os.path.exists(mp12):
    try:
        with open(mp12) as f: vm12 = json.load(f)
        for k in ["cpi","ppi","pmi_mfg","pmi_non_mfg","social_retail","volume_trend","etf","commodity"]:
            if k in vm12 and vm12[k]: macro[k] = vm12[k]
        log("v12: " + ", ".join(k+"="+str(len(macro[k])) for k in sorted(macro.keys()) if isinstance(macro[k],list) and macro[k]))
    except Exception as e: log("v12 macro ERR: " + str(e))

mp = os.path.join(BASE, '_macro.json')
if os.path.exists(mp):
    try:
        with open(mp) as f: vm = json.load(f)
        if "margin" in vm:
            for x in vm["margin"][-250:]: macro["margin"].append({"d":x["d"],"balance":x["balance"]})
        if "bond" in vm:
            for x in vm["bond"][-300:]: macro["bond_spread"].append({"d":x["d"],"v":x["spread"]})
        for k in ["pmi","m2","fed"]:
            if k in vm: macro[k] = vm[k]
    except Exception as e: log("v11 macro ERR: " + str(e))

# 3c. AKShare data
mp_ak = os.path.join(BASE, '_macro_akshare.json')
if os.path.exists(mp_ak):
    try:
        with open(mp_ak) as f: ak_data = json.load(f)
        # margin: balance in 元 → 亿; dedup; reformat YYYYMMDD → YYYY-MM-DD
        if ak_data.get("margin"):
            seen = set()
            dedup = []
            for x in ak_data["margin"]:
                d = x["d"]
                if d not in seen:
                    seen.add(d)
                    dedup.append({"d": d[:4]+"-"+d[4:6]+"-"+d[6:8], "balance": round(x["balance"]/1e8, 2)})
            macro["margin"] = dedup[-250:]
        # shibor: keep as is
        if ak_data.get("shibor"): macro["shibor"] = ak_data["shibor"][-250:]
        # lpr: rename y1 → v1y, y5 → v5y, filter NaN
        if ak_data.get("lpr"):
            import math
            lpr_raw = []
            for x in ak_data["lpr"]:
                v1 = x.get("y1"); v5 = x.get("y5")
                lpr_raw.append({"d": x["d"],
                    "v1y": v1 if (isinstance(v1, (int,float)) and not math.isnan(v1)) else None,
                    "v5y": v5 if (isinstance(v5, (int,float)) and not math.isnan(v5)) else None})
            macro["lpr"] = lpr_raw[-200:]
        # bond10y: dedup dates by keeping last value per date
        if ak_data.get("bond10y"):
            seen = {}
            for x in ak_data["bond10y"]:
                d = x["d"]
                if d not in seen: seen[d] = x["v"]
            macro["bond10y"] = [{"d": d, "v": v} for d, v in sorted(seen.items())][-250:]
        # m2: keep as is
        if ak_data.get("m2"): macro["m2"] = ak_data["m2"][-200:]
        log("akshare: " + ", ".join(k+"="+str(len(macro[k])) for k in ["margin","shibor","lpr","bond10y","m2"] if macro[k]))
    except Exception as e: log("akshare macro ERR: " + str(e))

# 4. Quotes — multi-source
print("4. Quotes...")
rt = {}
tt_volume = {}
tt_turnover = {}
tt_total_mv = {}
tt_circ_mv = {}

try:
    raw = http_get("https://api-ddc-wscn.xuangubao.cn/market/real?fields=prod_name,last_px,px_change,px_change_rate,high_px,low_px,open_px,turnover_volume&prod_code=000001.SH,399001.SZ,399006.SZ,000688.SH", t=10)
    xg = json.loads(raw)
    if xg.get("code") == 20000:
        snap = xg["data"]["snapshot"]
        xg_map = {"000001.SH":"000001","399001.SZ":"399001","399006.SZ":"399006","000688.SH":"000688"}
        for xc, code in xg_map.items():
            if xc not in snap: continue
            row = snap[xc]
            rt[code] = {"name":row[0],"price":round(row[1],2),"prev_close":0,"pct":round(row[3],2),
                        "open":round(row[6],2),"high":round(row[4],2),"low":round(row[5],2),
                        "volume":row[7] if len(row)>7 else 0}
        log(str(len(rt)) + " quotes OK from xuangubao")
except Exception as e: log("xuangubao: " + str(e))

try:
    raw_tt = http_get("http://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688", gbk=True, t=10)
    for line in raw_tt.strip().split("\n"):
        if not line.strip() or "=" not in line: continue
        try:
            body = line.split("=",1)[1].strip('";\n ')
            parts = body.split("~")
            if len(parts) < 45: continue
            c = parts[2].strip()
            tt_volume[c] = int(float(parts[6])) if parts[6] else 0
            tt_turnover[c] = float(parts[37]) if len(parts)>37 and parts[37] else 0
            tt_total_mv[c] = float(parts[43]) if len(parts)>43 and parts[43] else 0
            tt_circ_mv[c] = float(parts[44]) if len(parts)>44 and parts[44] else 0
        except: pass
    log("Tencent enrich: " + str(len(tt_volume)) + " codes")
except Exception as e: log("Tencent: " + str(e))

for code, _, _ in SYMBOLS:
    if code in rt: continue
    try:
        secid = ("1." if code.startswith(("0","6")) else "0.") + code
        raw = http_get("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14,f15,f16,f17,f18&secids=" + secid, t=10)
        items = json.loads(raw).get("data",{}).get("diff",[])
        for item in items:
            if not item or item.get("f12","") != code: continue
            price = float(item.get("f2",0) or 0)
            prev = float(item.get("f18",0) or 0) or price
            rt[code] = {"name":item.get("f14",""),"price":price,"prev_close":prev,
                        "pct":round((price-prev)/prev*100,2) if prev else 0,
                        "open":float(item.get("f17",0) or 0),"high":float(item.get("f15",0) or 0),
                        "low":float(item.get("f16",0) or 0),"volume":0}
    except Exception as e: log("EM " + code + ": " + str(e))

for code in rt:
    if code in tt_volume and tt_volume[code] > 0: rt[code]["volume"] = tt_volume[code]
    if code in tt_turnover and tt_turnover[code] > 0: rt[code]["turnover"] = tt_turnover[code]
    if code in tt_total_mv and tt_total_mv[code] > 0: rt[code]["total_mv"] = tt_total_mv[code]
    if code in tt_circ_mv and tt_circ_mv[code] > 0: rt[code]["circ_mv"] = tt_circ_mv[code]
    if rt[code].get("prev_close",0) == 0 and rt[code].get("pct",0) != 0:
        rt[code]["prev_close"] = round(rt[code]["price"]/(1+rt[code]["pct"]/100),2)

log("Quotes: " + str(len(rt)) + " total, enriched")

# 5. NBR + bond/sector indices
print("5. NBR & indices...")
nbr = {"sh_up":0,"sh_dn":0,"sz_up":0,"sz_dn":0,"sh_net":0,"sz_net":0,
       "bond_idx":{}, "sector_idx":{}}

try:
    raw = http_get("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f2,f3,f12", t=25)
    items = json.loads(raw).get('data',{}).get('diff',[])
    if items and len(items) > 100:
        for item in items:
            c = str(item.get('f12',''))
            pct = float(item.get('f3',0) or 0)
            if c.startswith(('60','688')):
                if pct > 0: nbr['sh_up'] += 1
                elif pct < 0: nbr['sh_dn'] += 1
            elif c.startswith(('00','30')):
                if pct > 0: nbr['sz_up'] += 1
                elif pct < 0: nbr['sz_dn'] += 1
        nbr['sh_net'] = round((nbr['sh_up']-nbr['sh_dn'])/max(1,nbr['sh_up']+nbr['sh_dn'])*100,1)
        nbr['sz_net'] = round((nbr['sz_up']-nbr['sz_dn'])/max(1,nbr['sz_up']+nbr['sz_dn'])*100,1)
        log("EM SH " + str(nbr['sh_up']) + "u/" + str(nbr['sh_dn']) + "d SZ " + str(nbr['sz_up']) + "u/" + str(nbr['sz_dn']) + "d")
except Exception as e: log("EM NBR: " + str(e))

if nbr['sh_net'] == 0 and nbr['sz_net'] == 0:
    for code in rt:
        pct = rt[code].get("pct",0)
        if code in ("000001","000688"): nbr['sh_net'] = round(pct,1) if nbr['sh_net'] == 0 else nbr['sh_net']
        elif code in ("399001","399006"): nbr['sz_net'] = round(pct,1) if nbr['sz_net'] == 0 else nbr['sz_net']
    log("NBR proxy: SH=" + str(nbr['sh_net']) + " SZ=" + str(nbr['sz_net']))

try:
    tt_bonds = http_get("http://qt.gtimg.cn/q=sz399481,sh000012,sz399986,sz399396,sz399989,sh000016,r_hkHSI,r_hkHSCEI", gbk=True, t=10)
    for line in tt_bonds.strip().split("\n"):
        if not line.strip() or "=" not in line: continue
        try:
            body = line.split("=",1)[1].strip('";\n ')
            parts = body.split("~")
            if len(parts) < 40: continue
            c = parts[2].strip()
            nm = parts[1] if parts[1] else c
            price = float(parts[3]) if parts[3] else 0
            prev = float(parts[4]) if parts[4] else price
            pct = round((price-prev)/prev*100,2) if prev else 0
            idx = {"name":nm,"price":price,"pct":pct}
            if c in ("000012","399481","399986"): nbr["bond_idx"][c] = idx
            else: nbr["sector_idx"][c] = idx
        except: pass
    log("Bond idx:" + str(len(nbr["bond_idx"])) + " sector:" + str(len(nbr["sector_idx"])))
except Exception as e: log("Bond indices: " + str(e))

# 6. Today's bar
print("6. Today bar...")
today_str = datetime.datetime.now(BJT).strftime('%Y-%m-%d')
for code, _, _ in SYMBOLS:
    q = rt.get(code, {})
    if not q or not q.get('price'): continue
    daily = kl_all[code].get('240', [])
    if not daily: continue
    last_d = daily[-1]['d'] if daily else ''
    if last_d == today_str: continue
    bar = {"d":today_str,"o":q.get('open',q['price']),"h":q.get('high',q['price']),
           "l":q.get('low',q['price']),"c":q['price'],"v":q.get('volume',0)}
    daily.append(bar)

# 7. Divergence detection
print("7. Divergence...")

def ema(data, n):
    r, k, prev = [], 2/(n+1), None
    for i, v in enumerate(data):
        if v is None: r.append(None); continue
        if prev is None:
            w = [x for x in data[max(0,i-n+1):i+1] if x is not None]
            prev = sum(w)/len(w) if w else v
        else: prev = v*k + prev*(1-k)
        r.append(prev)
    return r

def find_peaks(arr, w):
    return [i for i in range(w, len(arr)-w)
            if arr[i] is not None
            and all(arr[j] is None or arr[j] < arr[i] for j in range(i-w, i+w+1) if j != i)]

def find_valleys(arr, w):
    return [i for i in range(w, len(arr)-w)
            if arr[i] is not None
            and all(arr[j] is None or arr[j] > arr[i] for j in range(i-w, i+w+1) if j != i)]

def detect_recent_divergence(kl, max_days=90, max_per_type=5):
    if len(kl) < 20: return []
    closes = [b['c'] for b in kl]
    dif = []
    e12d, e26d = ema(closes, 12), ema(closes, 26)
    for i in range(len(kl)):
        dif.append(e12d[i]-e26d[i] if e12d[i] is not None and e26d[i] is not None else None)
    highs = [b['h'] for b in kl]
    lows = [b['l'] for b in kl]
    signals, seen = [], set()
    for dist in [5,7,10]:
        pp = find_peaks(highs, dist)
        pv = find_valleys(lows, dist)
        dp = find_peaks(dif, dist)
        dv = find_valleys(dif, dist)
        for i in range(len(pp)-1):
            p1, p2 = pp[i], pp[i+1]
            if p2-p1<3 or highs[p2]<=highs[p1]: continue
            for d1 in [d for d in dp if abs(d-p1)<=dist]:
                for d2 in [d for d in dp if abs(d-p2)<=dist]:
                    if d2<=d1 or dif[d2] is None or dif[d1] is None: continue
                    if dif[d2] < dif[d1]:
                        k = "top|" + kl[p2]['d']
                        if k not in seen:
                            seen.add(k)
                            price_lo = min(highs[p1],highs[p2])
                            price_hi = max(highs[p1],highs[p2])
                            signals.append({"type":"top","date":kl[p2]['d'],"prev_date":kl[p1]['d'],
                                "price":highs[p2],"prev_price":highs[p1],
                                "price_lo":price_lo,"price_hi":price_hi,
                                "dif":round(dif[d2],4),"prev_dif":round(dif[d1],4)})
        for i in range(len(pv)-1):
            v1, v2 = pv[i], pv[i+1]
            if v2-v1<3 or lows[v2]>=lows[v1]: continue
            for d1 in [d for d in dv if abs(d-v1)<=dist]:
                for d2 in [d for d in dv if abs(d-v2)<=dist]:
                    if d2<=d1 or dif[d2] is None or dif[d1] is None: continue
                    if dif[d2] > dif[d1]:
                        k = "bottom|" + kl[v2]['d']
                        if k not in seen:
                            seen.add(k)
                            price_lo = min(lows[v1],lows[v2])
                            price_hi = max(lows[v1],lows[v2])
                            signals.append({"type":"bottom","date":kl[v2]['d'],"prev_date":kl[v1]['d'],
                                "price":lows[v2],"prev_price":lows[v1],
                                "price_lo":price_lo,"price_hi":price_hi,
                                "dif":round(dif[d2],4),"prev_dif":round(dif[d1],4)})
    cutoff = (datetime.datetime.now(BJT) - datetime.timedelta(days=max_days)).strftime('%Y-%m-%d')
    recent = [s for s in signals if s['date'] >= cutoff]
    recent.sort(key=lambda x: x['date'], reverse=True)
    tops = [s for s in recent if s['type']=='top'][:max_per_type]
    bots = [s for s in recent if s['type']=='bottom'][:max_per_type]
    return sorted(tops+bots, key=lambda x: x['date'], reverse=True)

divergence, total_sigs = {}, 0
for code, _, name in SYMBOLS:
    dcode = {}
    for per in kl_all.get(code, {}):
        kl = kl_all[code][per]
        if len(kl) >= 20:
            sigs = detect_recent_divergence(kl)
            if sigs:
                dcode[per] = sigs
                total_sigs += len(sigs)
    if dcode: divergence[code] = dcode
log(str(total_sigs) + " signals")

# 8. Build HTML
print("8. Build HTML...")

# Deduplicate K-line bars
for code in kl_all:
    for per in kl_all[code]:
        seen = set()
        dedup = []
        for b in kl_all[code][per]:
            if b['d'] not in seen:
                seen.add(b['d'])
                dedup.append(b)
        kl_all[code][per] = dedup

payload = {
    "rt": rt, "kl": kl_all, "nbr": nbr,
    "period_names": {"15":"15m","30":"30m","60":"60m","240":"Day","1200":"Week"},
    "divergence": divergence, "macro": macro,
    "symbols": [{"code":c,"market":m,"name":n} for c,m,n in SYMBOLS],
    "ts": datetime.datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S'),
}

payload_json = json.dumps(payload, ensure_ascii=False, separators=(',',':'))

with open(os.path.join(BASE, 'template.html'), 'r', encoding='utf-8') as f:
    template = f.read()

html = template.replace('%%LWCHARTS%%', library)
html = html.replace('__PAYLOAD_JSON__', payload_json)

html = html.strip()
if '</script>' not in html[-200:]:
    html += '\n</script>'
if '</body>' not in html[-200:]:
    html += '\n</body>'
if '</html>' not in html[-200:]:
    html += '\n</html>'
html += '\n'

out = os.path.join(BASE, 'index.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)

so = html.count('<script>')
sc = html.count('</script>')
log("DONE: " + out + " (" + str(len(html)) + " bytes)")
log("scripts: " + str(so) + "/" + str(sc))
print("BUILD_COMPLETE")
          