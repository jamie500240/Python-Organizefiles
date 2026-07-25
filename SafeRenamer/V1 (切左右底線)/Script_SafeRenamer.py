# ==========================================================
# MODULE:      Script_SafeRenamer (切左右底線)
# PURPOSE:     安全批次改名工具：支援乾跑預演、字串切除、防撞名，採「先複製後驗證」非破壞性處理
# EXPORTS:     RenameFlow, NameProcessor, FileOps, Logger
# IMPORTS:     os, shutil, tkinter, pathlib, dataclasses, typing
# FORBIDDEN:   禁止直接對原始檔案執行 move 或 rename；禁止靜默吞沒例外 (except: pass)
# DEPENDENCIES: 內建標準庫 (無第三方套件依賴)
# VERSION:     1.0.1 [Stability: Frozen]
# ADR-001:     檔案佔用與鎖定簡化處理。遇到佔用或權限錯誤，直接記錄失敗並轉入失敗區，不實作暫存區排隊(Queue)機制。
# ADR-002:     原子性寫入原則 (All-or-Nothing)。若寫入成功區的檔案未能通過後續的大體驗證，必須在拋出例外前將其清除 (unlink)，防止髒資料污染成功區。
# ADR-003:     原歷史檔案有導致程式無法運行的空格；此外原 V1、V2、V3 差異較大，故另外列出備存。
# ==========================================================

import os
import shutil
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog
from typing import Final, List, Set, Tuple

# ==========================================
# 1. SET (開關與邏輯設定) - SSOT
# ==========================================
@dataclass
class RenameSettings:
    """使用者邏輯與字串處理設定 (純設定)"""
    LEFT_STRIP_ENABLED: bool = True
    LEFT_STRIP_INDEX: int = 1

    RIGHT_STRIP_ENABLED: bool = True
    RIGHT_STRIP_INDEX: int = 1

    SEPARATOR: str = "_"

# ==========================================
# 2. CONFIG (系統配置) - SSOT
# ==========================================
@dataclass
class AppConfig:
    """系統資料夾與效能預估配置 (純參數)"""
    SUCCESS_DIR_NAME: str = "檔案"
    FAIL_DIR_NAME: str = "改名失敗"
    LOG_FILE_NAME: str = "rename_log.txt"
    SPEED_MB_PER_SEC: int = 150

# ==========================================
# 3. STRING (介面與提示字串) - SSOT
# ==========================================
@dataclass
class AppStrings:
    """系統顯示文字庫 (純文本)"""
    SELECT_SOURCE: str = "【步驟 1】請選擇「想處理區」(來源資料夾)"
    SELECT_TARGET: str = "【步驟 2】請選擇「完成區」(目的資料夾)"
    ERR_SAME_DIR: str = "[FAIL FAST] 來源與目的資料夾不能相同！"
    ERR_NO_DIR: str = "[FAIL FAST] 未選擇資料夾，程式終止。"
    ERR_SETTING_IDX: str = "[FAIL FAST] INDEX 設定必須大於等於 1。"
    INFO_DRY_RUN: str = "\n=== [DRY RUN] 預覽結果 ==="
    INFO_EXECUTE: str = "\n=== 開始執行複製與改名 ==="
    PROMPT_CONTINUE: str = "\n請問是否要執行上述變更？(Y/N): "

# 常數初始化 (使用 Final 確保不被意外覆寫)
SET: Final[RenameSettings] = RenameSettings()
CONFIG: Final[AppConfig] = AppConfig()
STR: Final[AppStrings] = AppStrings()

# ==========================================
# 4. TOOLS / ACTION (純運算與單一職責元件)
# ==========================================
class NameProcessor:
    """負責檔名字串運算與正規化"""

    @staticmethod
    def normalize_filename(filename: str) -> str:
        """使用 Unicode \u3000 替換全形空白，並剔除前後不可見字元"""
        return filename.replace("\u3000", " ").strip()

    @staticmethod
    def generate_new_name(original_filename: str) -> str:
        """根據設定切割分隔符，計算並產生新檔名"""
        clean_filename: str = NameProcessor.normalize_filename(original_filename)
        name_part, ext_part = os.path.splitext(clean_filename)
        parts: List[str] = name_part.split(SET.SEPARATOR)

        required_underscores: int = 0
        if SET.LEFT_STRIP_ENABLED:
            required_underscores += SET.LEFT_STRIP_INDEX
        if SET.RIGHT_STRIP_ENABLED:
            required_underscores += SET.RIGHT_STRIP_INDEX

        # 份數不夠切除時，安全退回原檔名
        if len(parts) <= required_underscores:
            return clean_filename

        start_idx: int = SET.LEFT_STRIP_INDEX if SET.LEFT_STRIP_ENABLED else 0
        end_idx: int = len(parts) - (SET.RIGHT_STRIP_INDEX if SET.RIGHT_STRIP_ENABLED else 0)

        new_name_part: str = SET.SEPARATOR.join(parts[start_idx:end_idx])
        return f"{new_name_part}{ext_part}"


class FileOps:
    """負責檔案系統操作與防撞名計算"""

    @staticmethod
    def get_safe_target_path(target_dir: Path, new_name: str, used_names_in_run: Set[str]) -> Path:
        """防撞名邏輯：若檔名重複，自動加上 _1, _2 遞增序號"""
        name_part, ext_part = os.path.splitext(new_name)
        counter: int = 1
        final_name: str = new_name

        while (target_dir / final_name).exists() or (final_name in used_names_in_run):
            final_name = f"{name_part}_{counter}{ext_part}"
            counter += 1

        used_names_in_run.add(final_name)
        return target_dir / final_name


class Logger:
    """負責日誌寫入，支援 context manager (with 語句)"""

    def __init__(self, log_path: Path):
        self.log_path: Path = log_path
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write("=== 批次改名日誌 ===\n")

    def write(self, msg: str) -> None:
        """追加寫入日誌訊息"""
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f"{msg}\n")

# ==========================================
# 5. FLOW (主流程控制中心)
# ==========================================
class RenameFlow:
    """協調來源、目的、預覽與執行流程"""

    def __init__(self):
        self.source_dir: Path = Path()
        self.target_dir: Path = Path()
        self.success_dir: Path = Path()
        self.fail_dir: Path = Path()
        self.file_list: List[Path] = []

    def validate_settings(self) -> None:
        """Fail-Fast 檢核設定數值是否合法"""
        if SET.LEFT_STRIP_ENABLED and SET.LEFT_STRIP_INDEX < 1:
            raise ValueError(STR.ERR_SETTING_IDX)
        if SET.RIGHT_STRIP_ENABLED and SET.RIGHT_STRIP_INDEX < 1:
            raise ValueError(STR.ERR_SETTING_IDX)

    def select_directories(self) -> None:
        """透過 GUI 選擇來源與目的目錄，並隨即釋放 GUI 資源"""
        root = tk.Tk()
        root.withdraw()
        try:
            print(STR.SELECT_SOURCE)
            src: str = filedialog.askdirectory(title=STR.SELECT_SOURCE)
            if not src:
                raise SystemExit(STR.ERR_NO_DIR)

            print(STR.SELECT_TARGET)
            tgt: str = filedialog.askdirectory(title=STR.SELECT_TARGET)
            if not tgt:
                raise SystemExit(STR.ERR_NO_DIR)
        finally:
            root.destroy()  # 確保 Tk 資源被安全釋放

        self.source_dir = Path(src)
        self.target_dir = Path(tgt)

        if self.source_dir.resolve() == self.target_dir.resolve():
            raise SystemExit(STR.ERR_SAME_DIR)

        self.success_dir = self.target_dir / CONFIG.SUCCESS_DIR_NAME
        self.fail_dir = self.target_dir / CONFIG.FAIL_DIR_NAME

        self.file_list = [f for f in self.source_dir.iterdir() if f.is_file()]

    def dry_run(self) -> List[Tuple[Path, str]]:
        """預演模式：印出改名前後對照表，計算檔案大小與預估耗時"""
        print(STR.INFO_DRY_RUN)
        total_size_bytes: int = 0
        used_names: Set[str] = set()
        plan: List[Tuple[Path, str]] = []

        for file_path in self.file_list:
            total_size_bytes += file_path.stat().st_size

            base_new_name: str = NameProcessor.generate_new_name(file_path.name)
            safe_path: Path = FileOps.get_safe_target_path(self.success_dir, base_new_name, used_names)

            plan.append((file_path, safe_path.name))

            status: str = "[變更]" if file_path.name != safe_path.name else "[原封]"
            print(f"{status} {file_path.name}  ➔  {safe_path.name}")

        total_mb: float = total_size_bytes / (1024 * 1024)
        est_seconds: int = max(1, int(total_mb / CONFIG.SPEED_MB_PER_SEC))

        print(f"\n[統計] 共 {len(self.file_list)} 個檔案，總大小約 {total_mb:.2f} MB。")
        print(f"[預估] 以 {CONFIG.SPEED_MB_PER_SEC} MB/s 計算，複製大約需要 {est_seconds} 秒。")

        return plan

    def execute(self, plan: List[Tuple[Path, str]]) -> None:
        """正式執行非破壞性複製與安全驗證"""
        print(STR.INFO_EXECUTE)
        self.success_dir.mkdir(parents=True, exist_ok=True)
        self.fail_dir.mkdir(parents=True, exist_ok=True)

        logger: Logger = Logger(self.target_dir / CONFIG.LOG_FILE_NAME)

        success_count: int = 0
        fail_count: int = 0

        for original_path, new_name in plan:
            target_file_path: Path = self.success_dir / new_name
            try:
                # 複製檔案 (保留 Timestamp 等後設資料)
                shutil.copy2(original_path, target_file_path)

                # ADR-002: 原子性寫入驗證 (強健性大小比對)
                if original_path.stat().st_size != target_file_path.stat().st_size:
                    error_msg: str = f"檔案驗證失敗：來源 ({original_path.stat().st_size} bytes) 與目的大小不符。"
                    try:
                        target_file_path.unlink(missing_ok=True)
                        error_msg += "已成功清除殘檔。"
                    except OSError as unlink_e:
                        error_msg += f"【嚴重警告】清除殘檔失敗 ({str(unlink_e)})，成功區可能殘留髒資料！"

                    raise IOError(error_msg)

                logger.write(f"[SUCCESS] {original_path.name} -> {new_name}")
                success_count += 1

            except (IOError, OSError, PermissionError) as e:
                logger.write(f"[FAIL] {original_path.name} | Error: {str(e)}")
                fail_count += 1
                try:
                    # 隔離原則：將處理異常的原始檔案備份至失敗區
                    shutil.copy2(original_path, self.fail_dir / original_path.name)
                except (IOError, OSError, PermissionError) as nested_e:
                    critical_err: str = f"[CRITICAL] 檔案 {original_path.name} 寫入失敗區發生嚴重異常: {str(nested_e)}"
                    print(critical_err)
                    logger.write(critical_err)

        print(f"\n✅ 執行完畢！成功: {success_count}，失敗: {fail_count}。")
        print(f"📄 請至 {self.target_dir.resolve()} 查看完成結果與 Log。")

# ==========================================
# 6. MAIN (Single Entry Point Coordinator)
# ==========================================
def main() -> None:
    """單一入口協調器，僅處理調度，不夾帶業務邏輯"""
    flow: RenameFlow = RenameFlow()

    try:
        flow.validate_settings()
        flow.select_directories()

        if not flow.file_list:
            print("[資訊] 來源資料夾中沒有任何檔案。")
            return

        execution_plan: List[Tuple[Path, str]] = flow.dry_run()

        user_input: str = input(STR.PROMPT_CONTINUE).strip().upper()
        if user_input == 'Y':
            flow.execute(execution_plan)
        else:
            print("\n[終止] 使用者取消操作，未進行任何變更。")

    except ValueError as ve:
        print(f"[設定錯誤] {ve}")
    except SystemExit as se:
        print(se)
    except Exception as e:
        print(f"\n[未預期系統錯誤] {str(e)}")


if __name__ == "__main__":
    main()
