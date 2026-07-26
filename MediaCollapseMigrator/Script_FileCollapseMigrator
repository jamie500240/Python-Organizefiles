# ==========================================================
# MODULE:       Script_FileCollapseMigrator
# PURPOSE:      自動掃描提取檔案 DNA 並分流所有檔案。具備極限防禦、斷點自癒與全圖形化介面。
# EXPORTS:      Script_FileCollapseMigrator
# IMPORTS:      shutil, csv, hashlib, logging, time, pathlib, re, threading, tkinter, json, sys
# FORBIDDEN:    禁止修改來源檔案（唯讀模式）、禁止 Console 輸入、禁止返回 None/空值。
# DEPENDENCIES: PIL, numpy, tqdm
# VERSION:      1.0.0 [Stability: Experimental]
# ==========================================================

import sys
import shutil
import time
import re
import csv
import json
import hashlib
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Final, Dict, Any, List, Set, Tuple
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm
from PIL import Image
import numpy as np

# --- [config: 純設定 - 全大寫] ---
CONFIG_THRESH_BASE: Final[int] = 42
CONFIG_THRESH_AI: Final[int] = 130
CONFIG_ENTROPY_AI: Final[float] = 6.2
CONFIG_LV1_DATE_MIN: Final[int] = 2
CONFIG_MAX_DIR_LEN: Final[int] = 50
CONFIG_MAX_FILE_LEN: Final[int] = 60
CONFIG_FAILED_DIR: Final[str] = "[FAILED_TO_PROCESS]"

# --- [Setting: 純參數] ---
SETTING_CHUNK_SIZE: Final[int] = 4096
SETTING_EPSILON: Final[float] = 1e-7
SETTING_STATE_FILE: Final[str] = "migration_state_checkpoint.json"

# --- [Mapping: 純對照] ---
CATEGORY_MAP: Final[Dict[Tuple[str, str], Set[str]]] = {
    ('Documents', 'WORD'): {'.doc', '.docx', '.docm', '.odt', '.rtf', '.pages', '.wps'},
    ('Documents', 'EXCEL'): {'.xls', '.xlsx', '.ods', '.csv', '.numbers', '.tsv'},
    ('Documents', 'PPT'): {'.ppt', '.pptx', '.pptm', '.odp', '.key'},
    ('Documents', 'TXT'): {'.txt', '.md', '.log', '.rst'},
    ('Documents', 'PDF'): {'.pdf'},
    ('CODE', 'SCRIPTS'): {
        '.py', '.js', '.ts', '.html', '.css', '.cpp', '.c', '.h', '.cs', 
        '.java', '.php', '.sh', '.bat', '.ps1', '.vbs', '.vba', '.xlsm', 
        '.xltm', '.json', '.yaml', '.yml', '.sql', '.ipynb', '.r'
    },
    ('Images', 'PHOTO'): {'.jpg', '.jpeg', '.jfif', '.png', '.gif', '.webp', '.heic', '.bmp', '.tiff'},
    ('Videos', 'VIDEO'): {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv'},
    ('Audio', 'AUDIO'): {'.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg'},
    ('Archives', 'COMPRESSED'): {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Script_FileCollapseMigrator:
    def __init__(self, source_path: str, dest_path: str):
        # 初始化、路徑清潔 (Windows 極限路徑防禦)
        self.root: Path = self._apply_path_defense(Path(source_path).resolve())
        self.timestamp: str = time.strftime('%H%M%S')
        
        # 輸出落腳點建構
        base_dest = self._apply_path_defense(Path(dest_path).resolve())
        self.export_root: Path = base_dest / f"[MEDIA_VAULT]_{self.timestamp}"
        self.checkpoint_path: Path = self.export_root / SETTING_STATE_FILE
        
        self.human_tags: set = set()
        self.tags_lock: threading.Lock = threading.Lock()
        self.traceability_log: List[Dict[str, str]] = []
        self.log_lock: threading.Lock = threading.Lock()

    # ==========================================
    # 初始化與防禦區塊 (Init & Env Check)
    # ==========================================
    def _apply_path_defense(self, raw_path: Path) -> Path:
        """[極限防禦] 解決 Windows 260 字元路徑限制"""
        if sys.platform == 'win32' and not str(raw_path).startswith('\\\\?\\'):
            return Path(f"\\\\?\\{str(raw_path)}")
        return raw_path

    def _calculate_md5(self, file_path: Path) -> str:
        """[工具] 計算檔案 MD5，供安全移動比對使用"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(SETTING_CHUNK_SIZE), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    # ==========================================
    # 純運算區塊 (Tools - 單一職責、解耦)
    # ==========================================
    def _get_dna(self, fpath: Path) -> Dict[str, Any]:
        """[純運算] DNA 萃取。嚴禁回傳 None 或 空值。"""
        try:
            stat = fpath.stat()
            rel = fpath.relative_to(self.root).parts
            raw_tag: str = str(rel[0]) if len(rel) > 1 else "NO_TAG"
            is_human: bool = (raw_tag != "NO_TAG") and not bool(re.match(r'^\d{4,8}$', raw_tag))
            
            if is_human:
                with self.tags_lock:
                    self.human_tags.add(raw_tag)
            
            file_date: str = time.strftime("%Y%m%d", time.localtime(stat.st_mtime))
            ext: str = fpath.suffix.lower()
            
            main_cat: str = "Others"
            sub_cat: str = "MISC"
            for (m_cat, s_cat), exts in CATEGORY_MAP.items():
                if ext in exts:
                    main_cat, sub_cat = m_cat, s_cat
                    break

            is_img: bool = (main_cat == 'Images')
            dna: Dict[str, Any] = {
                "file_path": str(fpath), 
                "tag": raw_tag, 
                "is_human": is_human, 
                "date": file_date, 
                "main_cat": main_cat,
                "sub_cat": sub_cat,
                "is_img": is_img, 
                "ai_code": "NO_CODE",
                "error": "SUCCESS",
                "failed": False
            }
            
            if is_img:
                with Image.open(fpath) as img:
                    exif = img.getexif()
                    if exif and 306 in exif: 
                        file_date = exif[306].split(' ')[0].replace(':', '')
                    
                    gray = img.convert('L')
                    hist, _ = np.histogram(np.array(gray), bins=256, range=(0, 255))
                    p = hist / (hist.sum() + SETTING_EPSILON)
                    ent = -np.sum(p * np.log2(p + SETTING_EPSILON))
                    
                    if ent < CONFIG_ENTROPY_AI:
                        dna["ai_code"] = "_A"
                    dna["date"] = file_date
            
            return dna

        except Exception as e:
            return {
                "file_path": str(fpath), 
                "is_img": False, 
                "error": f"DNA_ERROR: {str(e)}", 
                "failed": True,
                "ai_code": "NO_CODE"
            }

    # ==========================================
    # 實體 IO 動作 (Strict IO Segregation)
    # ==========================================
    def _safe_copy_from_source(self, src: Path, dest: Path) -> Path:
        """[跨區複製] 保留來源原檔。複製 -> MD5 比對確認。"""
        src = self._apply_path_defense(src)
        dest = self._apply_path_defense(dest)
        
        if dest.exists() and dest != src:
            dest = dest.parent / f"{src.stem}_{self.timestamp}{src.suffix}"
        
        shutil.copy2(src, dest)
        
        if dest.stat().st_size == src.stat().st_size and self._calculate_md5(dest) == self._calculate_md5(src):
            return dest
        else:
            if dest.exists():
                dest.unlink()
            raise IOError(f"檔案複製驗證失敗: {src}")

    def _safe_internal_move(self, src: Path, dest: Path) -> Path:
        """[內部搬移] 僅在落腳點內使用。複製 -> MD5 比對 -> 刪除內部原檔。"""
        src = self._apply_path_defense(src)
        dest = self._apply_path_defense(dest)
        
        if dest.exists() and dest != src:
            dest = dest.parent / f"{src.stem}_{self.timestamp}{src.suffix}"
        
        shutil.copy2(src, dest)
        
        if dest.stat().st_size == src.stat().st_size and self._calculate_md5(dest) == self._calculate_md5(src):
            src.unlink()
            return dest
        else:
            if dest.exists():
                dest.unlink()
            raise IOError(f"內部搬移驗證失敗，檔案保留原狀: {src}")

    # ==========================================
    # 單一入口 (Single Entry Point)
    # ==========================================
    def execute_with_coordinator(self) -> None:
        """流程協調器：Init -> Collect -> Plan -> Confirm -> Execute -> Cleanup"""
        logging.info("啟動安全移轉流程 (來源唯讀模式)...")
        
        try:
            # 1. Init & Env check
            assert self.root.exists(), f"來源路徑不存在: {self.root}"
            self.export_root.mkdir(parents=True, exist_ok=True)
            
            # 2. 斷點續跑檢查 (自癒機制)
            if self.checkpoint_path.exists():
                logging.info("載入中斷快照...")
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    dna_pool = json.load(f)
            else:
                # 3. 採集 DNA (純運算)
                all_files = [f for f in self.root.rglob("*") if f.is_file() and f.name != SETTING_STATE_FILE]
                with ThreadPoolExecutor() as exc:
                    dna_pool = list(tqdm(exc.map(self._get_dna, all_files), total=len(all_files), desc="DNA 採集"))
                
                with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                    json.dump(dna_pool, f, ensure_ascii=False, indent=4)
            
            # 4. 規劃階段 (準備 Dry-Run 資料)
            total_bytes: int = sum(Path(i["file_path"]).stat().st_size for i in dna_pool if Path(i["file_path"]).exists())
            total_gb: float = total_bytes / (1024 ** 3)
            
            # 5. 強制 Dry-Run
            msg = (f"🔍 掃描完畢！來源檔案將安全保留。\n\n"
                   f"預計複製檔案: {len(dna_pool):,} 個\n"
                   f"總資料量約: {total_gb:.2f} GB\n\n"
                   f"是否確認將資料複製至落腳點並進行結構坍塌？")
            assert messagebox.askyesno("Dry-Run 確認", msg), "使用者取消執行。"
            
            # 6. 執行 IO
            logging.info("開始複製並路由檔案...")
            self._execute_routing(dna_pool)
            self._run_greedy_collapse()

        except AssertionError as ae:
            logging.warning(f"[流程終止] {ae}")
            messagebox.showwarning("中止提示", str(ae))
        except Exception as e:
            logging.critical(f"[未預期異常] {e}")
            messagebox.showerror("嚴重錯誤", f"系統發生例外狀況：\n{e}")
        else:
            if self.checkpoint_path.exists():
                self.checkpoint_path.unlink()
            messagebox.showinfo("執行成功", f"🎉 作業完成！原資料夾未受影響。\n輸出位置：\n{self.export_root}")
        finally:
            # 7. Cleanup & Reporting
            self._eradicate_tunnels()
            self._generate_traceability_report()
            logging.info("清理與報表生成完畢，程序結束。")

    # ==========================================
    # 內部邏輯與清理 (Tools & Cleanup)
    # ==========================================
    def _execute_routing(self, dna_pool: List[Dict[str, Any]]) -> None:
        """[路由] 使用 _safe_copy_from_source 從原處複製到落腳點"""
        umbrella_bins: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        
        for item in dna_pool:
            if item["failed"]:
                q_dir = self.export_root / CONFIG_FAILED_DIR
                q_dir.mkdir(parents=True, exist_ok=True)
                src_p = Path(item["file_path"])
                if src_p.exists():
                    actual_dest = self._safe_copy_from_source(src_p, q_dir / src_p.name)
                    self._record_log(src_p, actual_dest, False, "NO_CODE", item["error"])
                continue

            m_cat, s_cat = item["main_cat"], item["sub_cat"]
            u_key = item["tag"] if item["is_human"] else item["date"]
            umbrella_bins.setdefault((m_cat, s_cat, u_key), []).append(item)

        for (m_cat, s_cat, u_name), items in tqdm(umbrella_bins.items(), desc="檔案複製中"):
            clean_u_name = re.sub(r'[\\/:*?"<>|]', '_', str(u_name)).strip()
            u_dir = self.export_root / m_cat / s_cat / clean_u_name[:CONFIG_MAX_DIR_LEN]
            u_dir.mkdir(parents=True, exist_ok=True)
            
            for it in items:
                src_p = Path(it["file_path"])
                if not src_p.exists():
                    continue
                    
                clean_stem = "".join(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', src_p.stem))
                ai_str = it["ai_code"] if it["ai_code"] != "NO_CODE" else ""
                new_name = f"[{it['date']}]{ai_str}{clean_stem[:CONFIG_MAX_FILE_LEN]}{src_p.suffix}"
                
                try:
                    actual_dest = self._safe_copy_from_source(src_p, u_dir / new_name)
                    self._record_log(src_p, actual_dest, it["is_img"], it["ai_code"], "SUCCESS")
                except Exception as e:
                    self._record_log(src_p, u_dir / new_name, it["is_img"], it["ai_code"], f"COPY_FAIL: {e}")

    def _run_greedy_collapse(self) -> None:
        """[坍塌] 在落腳點內部進行貪婪平攤 (使用內部安全搬移)"""
        for main_dir in self.export_root.iterdir():
            if main_dir.is_dir() and main_dir.name != CONFIG_FAILED_DIR:
                for sub_dir in main_dir.iterdir():
                    if sub_dir.is_dir():
                        self._apply_collapse_logic(sub_dir)

    def _apply_collapse_logic(self, target_root: Path) -> None:
        """原坍塌邏輯：失敗即觸發原子性回滾"""
        for _ in range(5): 
            all_dirs = sorted([d for d in target_root.rglob("*") if d.is_dir()], 
                              key=lambda x: len(x.parts), reverse=True)
            for d in all_dirs:
                if not d.exists() or d == target_root or d.name == CONFIG_FAILED_DIR:
                    continue
                
                content = list(d.iterdir())
                files = [f for f in content if f.is_file()]
                depth = len(d.relative_to(target_root).parts)
                is_human = d.name in self.human_tags and depth == 1

                if len(files) == 0 or (depth == 1 and not is_human and re.match(r'^\d{4,8}(_.*)?$', d.name) and len(files) < CONFIG_LV1_DATE_MIN):
                    moved_records = []
                    try:
                        for item in content:
                            dest_path = d.parent / item.name
                            actual_dest = self._safe_internal_move(item, dest_path)
                            moved_records.append((actual_dest, item))
                        try: d.rmdir()
                        except OSError: pass
                    except Exception as e:
                        logging.error(f"坍塌回滾: {d} | Error: {e}")
                        for current_loc, original_loc in moved_records:
                            if current_loc.exists():
                                self._safe_internal_move(current_loc, original_loc)
                        raise RuntimeError(f"目錄 {d} 坍塌終止。") from e

    def _eradicate_tunnels(self) -> None:
        """
        [Cleanup] 撲滅資料夾隧道
        掃描所有資料夾，若裡面只有「唯一一個資料夾且無檔案」，則將下層內容提拔並銷毀空殼。
        """
        logging.info("開始掃描並撲滅無意義的資料夾隧道...")
        for _ in range(3): # 多層次掃描以應對深層隧道
            all_dirs = sorted([d for d in self.export_root.rglob("*") if d.is_dir()],
                              key=lambda x: len(x.parts), reverse=True)
            for d in all_dirs:
                if not d.exists() or d == self.export_root:
                    continue
                
                items = list(d.iterdir())
                # 隧道特徵：長度為 1 且該唯一物件是資料夾
                if len(items) == 1 and items[0].is_dir():
                    tunnel_child = items[0]
                    for target in tunnel_child.iterdir():
                        self._safe_internal_move(target, d / target.name)
                    try:
                        tunnel_child.rmdir()
                    except OSError:
                        pass

    def _record_log(self, src: Path, dest: Path, is_img: bool, ai_flag: str, error: str) -> None:
        with self.log_lock:
            self.traceability_log.append({
                "src": str(src), "dest": str(dest), "is_img": str(is_img), 
                "ai_flag": ai_flag, "error": error
            })

    def _generate_traceability_report(self) -> None:
        if not self.traceability_log:
            return
        report_path = self.export_root / f"Migration_Traceability_{self.timestamp}.csv"
        try:
            with open(report_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["Original Path", "New Path", "Is Image", "AI Flag", "Error"])
                for log in self.traceability_log:
                    writer.writerow([
                        log.get('src', 'NO_SRC'), log.get('dest', 'NO_DEST'), 
                        log.get('is_img', 'False'), log.get('ai_flag', 'NO_CODE'), log.get('error', 'UNKNOWN')
                    ])
        except Exception as e:
            logging.error(f"報表生成失敗: {e}")

# ==========================================
# 啟動區塊 (全圖形化、防呆引導)
# ==========================================
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw() 
    
    # [步驟一] 選擇來源
    messagebox.showinfo("步驟 1/2", "請選擇「來源資料夾」\n(系統將以唯讀模式掃描，絕不修改原檔案)")
    src_path = filedialog.askdirectory(title="[1/2] 選擇來源資料夾 (唯讀)")
    if not src_path:
        sys.exit(0)
        
    # [步驟二] 選擇落腳點
    messagebox.showinfo("步驟 2/2", "請選擇「輸出落腳點」\n(整理好的結構將會完整複製到此處)")
    dest_path = filedialog.askdirectory(title="[2/2] 選擇輸出落腳點")
    if not dest_path:
        sys.exit(0)
        
    # [防呆驗證] 落腳點不能跟來源相同，也不能在來源資料夾裡面
    try:
        if Path(dest_path).resolve() == Path(src_path).resolve():
            raise ValueError("落腳點不可與來源資料夾相同！")
        if Path(dest_path).resolve().is_relative_to(Path(src_path).resolve()):
            raise ValueError("落腳點不可建立在來源資料夾內部！")
    except ValueError as e:
        messagebox.showerror("路徑設定錯誤", str(e))
        sys.exit(1)

    app = Script_FileCollapseMigrator(src_path, dest_path)
    app.execute_with_coordinator()
