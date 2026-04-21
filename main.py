import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path


class ClaudeSessionMigrator:
    APP_VERSION = "v1.0.0"

    def __init__(self, root):
        self.root = root
        self.root.title(f"Claude Code 会话迁移工具 {self.APP_VERSION}")
        self.root.geometry("700x520")
        self.root.resizable(False, False)

        self.claude_projects_dir = Path.home() / ".claude" / "projects"

        self._build_ui()
        self._load_sessions()

    def _build_ui(self):
        # 顶部说明
        info_frame = ttk.LabelFrame(self.root, text="说明", padding=10)
        info_frame.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(
            info_frame,
            text="将 Claude Code 的会话数据从旧项目路径迁移到新项目路径，移动项目文件夹后会话不丢失。",
            wraplength=660,
        ).pack()

        # 路径选择区域
        path_frame = ttk.LabelFrame(self.root, text="路径配置", padding=10)
        path_frame.pack(fill="x", padx=10, pady=5)

        # 原目录
        ttk.Label(path_frame, text="原项目目录:").grid(row=0, column=0, sticky="w", pady=5)
        self.old_path_var = tk.StringVar()
        self.matched_dir_var = tk.StringVar(value="(未匹配)")
        old_entry = ttk.Entry(path_frame, textvariable=self.old_path_var, width=60)
        old_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(path_frame, text="浏览", command=self._browse_old, width=6).grid(row=0, column=2, pady=5)
        ttk.Label(path_frame, text="匹配会话目录名:").grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Label(path_frame, textvariable=self.matched_dir_var).grid(row=2, column=1, columnspan=2, sticky="w", pady=(5, 0))

        # 新目录
        ttk.Label(path_frame, text="新项目目录:").grid(row=1, column=0, sticky="w", pady=5)
        self.new_path_var = tk.StringVar()
        new_entry = ttk.Entry(path_frame, textvariable=self.new_path_var, width=60)
        new_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(path_frame, text="浏览", command=self._browse_new, width=6).grid(row=1, column=2, pady=5)

        # 操作按钮
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=5)

        self.mode_var = tk.StringVar(value="copy")
        ttk.Radiobutton(btn_frame, text="复制(保留)", variable=self.mode_var, value="copy").pack(side="left", padx=10)
        ttk.Radiobutton(btn_frame, text="移动(删除原)", variable=self.mode_var, value="move").pack(side="left", padx=10)
        ttk.Button(btn_frame, text="打开配置目录", command=self._open_config_dir).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="刷新", command=self._refresh_old_mapping).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="删除", command=self._delete_session_dir).pack(side="left", padx=5)

        ttk.Button(btn_frame, text="执行迁移", command=self._migrate).pack(side="right", padx=10)

        # 已有会话列表
        list_frame = ttk.LabelFrame(self.root, text="已有会话目录 (点击可自动填入原路径)", padding=10)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        columns = ("encoded", "decoded")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        self.tree.heading("encoded", text="目录名")
        self.tree.heading("decoded", text="推测的项目路径")
        self.tree.column("encoded", width=280)
        self.tree.column("decoded", width=380)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_session_select)

    def _encode_path(self, path_str):
        """将路径编码为 Claude 的目录名格式"""
        p = path_str.replace("\\", "/").rstrip("/")
        # 约定编码规则：
        # 1) Windows 盘符后使用 "--"（如 d:/work -> d--work）
        # 2) 路径分隔符 "/" 使用 "-"
        # 3) 原始目录名中的 "_" 在编码中同样记作 "-"
        if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
            drive = p[0].lower()
            rest = p[2:].lstrip("/")
            normalized_rest = rest.replace("_", "-").replace("/", "-")
            return f"{drive}--{normalized_rest}" if normalized_rest else f"{drive}--"
        return p.replace("_", "-").replace("/", "-").lstrip("-")

    def _decode_dirname(self, dirname):
        """尝试从目录名推测原始路径"""
        # 注意: 由于 "_" 与 "/" 都编码为 "-"，反向推测仅供展示参考
        if len(dirname) >= 3 and dirname[1:3] == "--" and dirname[0].isalpha():
            drive = dirname[0].upper()
            rest = dirname[3:].replace("-", "\\")
            return f"{drive}:\\" + rest if rest else f"{drive}:\\"
        return "/" + dirname.replace("-", "/")

    def _normalize_for_compare(self, path_str):
        p = path_str.replace("\\", "/").rstrip("/").lower()
        if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
            drive = p[0]
            rest = p[2:].lstrip("/")
            rest = rest.replace("_", "-")
            return f"{drive}--{rest.replace('/', '-')}" if rest else f"{drive}--"
        return p.replace("_", "-").replace("/", "-").lstrip("-")

    def _find_matching_session_dir(self, path_str):
        """在已有会话目录中查找匹配的目录名"""
        if not self.claude_projects_dir.exists():
            return None

        encoded = self._encode_path(path_str)
        # 精确匹配
        target = self.claude_projects_dir / encoded
        if target.exists():
            return encoded

        # 模糊匹配：将 "_" 与 "-" 视作等价后比较
        normalized = self._normalize_for_compare(path_str)
        for d in self.claude_projects_dir.iterdir():
            if d.is_dir():
                current = d.name.lower()
                if current == normalized:
                    return d.name
                # 兼容旧目录格式: d-work-project（盘符后单 "-"）
                if len(normalized) >= 3 and normalized[1:3] == "--":
                    legacy = normalized[0] + "-" + normalized[3:]
                    if current == legacy:
                        return d.name
                if current.replace("_", "-") == normalized.replace("_", "-"):
                    return d.name

        return None

    def _load_sessions(self):
        """加载已有的会话目录列表"""
        self.tree.delete(*self.tree.get_children())
        if not self.claude_projects_dir.exists():
            return
        for d in sorted(self.claude_projects_dir.iterdir()):
            if d.is_dir():
                decoded = self._decode_dirname(d.name)
                self.tree.insert("", "end", values=(d.name, decoded))

    def _on_session_select(self, event):
        selected = self.tree.selection()
        if selected:
            item = self.tree.item(selected[0])
            decoded_path = item["values"][1]
            self.old_path_var.set(decoded_path)
            self.matched_dir_var.set(item["values"][0])

    def _browse_old(self):
        path = filedialog.askdirectory(title="选择原项目目录")
        if path:
            self.old_path_var.set(path)
            self._refresh_old_mapping()

    def _browse_new(self):
        path = filedialog.askdirectory(title="选择新项目目录")
        if path:
            self.new_path_var.set(path)

    def _refresh_old_mapping(self):
        old_path = self.old_path_var.get().strip()
        if not old_path:
            self.matched_dir_var.set("(未匹配)")
            messagebox.showwarning("提示", "请先填写原项目目录")
            return

        old_dir = self._find_matching_session_dir(old_path)
        if old_dir:
            self.matched_dir_var.set(old_dir)
            messagebox.showinfo("刷新完成", f"已匹配到会话目录:\n{old_dir}")
            return

        encoded = self._encode_path(old_path)
        self.matched_dir_var.set("(未匹配)")
        messagebox.showwarning(
            "未匹配到目录",
            f"未找到对应会话目录。\n\n原路径: {old_path}\n按规则编码: {encoded}",
        )

    def _open_config_dir(self):
        config_dir = self.claude_projects_dir
        if not config_dir.exists():
            messagebox.showwarning("提示", f"配置目录不存在:\n{config_dir}")
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(config_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(config_dir)], check=True)
            else:
                subprocess.run(["xdg-open", str(config_dir)], check=True)
        except Exception as e:
            messagebox.showerror("错误", f"打开配置目录失败:\n{e}")

    def _delete_session_dir(self):
        old_path = self.old_path_var.get().strip()
        if not old_path:
            messagebox.showwarning("提示", "请先填写原项目目录")
            return

        old_dir = self._find_matching_session_dir(old_path)
        if not old_dir:
            encoded = self._encode_path(old_path)
            messagebox.showerror(
                "错误",
                f"未找到要删除的会话目录。\n\n原路径: {old_path}\n按规则编码: {encoded}",
            )
            return

        target = self.claude_projects_dir / old_dir
        confirm = messagebox.askyesno(
            "确认删除",
            f"将删除以下会话目录（不可恢复）:\n{target}\n\n是否继续？",
        )
        if not confirm:
            return

        try:
            shutil.rmtree(target)
            self._load_sessions()
            self.matched_dir_var.set("(未匹配)")
            messagebox.showinfo("完成", f"已删除会话目录:\n{target}")
        except Exception as e:
            messagebox.showerror("错误", f"删除失败:\n{e}")

    def _migrate(self):
        old_path = self.old_path_var.get().strip()
        new_path = self.new_path_var.get().strip()

        if not old_path or not new_path:
            messagebox.showwarning("提示", "请填写原目录和新目录路径")
            return

        old_dir = self._find_matching_session_dir(old_path)
        if not old_dir:
            messagebox.showerror("错误", "未找到原路径对应的会话目录，请确认路径是否正确。")
            return

        new_encoded = self._encode_path(new_path)
        src = self.claude_projects_dir / old_dir
        dst = self.claude_projects_dir / new_encoded

        if dst.exists():
            overwrite = messagebox.askyesno("确认", f"目标会话目录已存在:\n{dst}\n\n是否覆盖？")
            if not overwrite:
                return
            shutil.rmtree(dst)

        try:
            if self.mode_var.get() == "copy":
                shutil.copytree(src, dst)
                messagebox.showinfo("完成", f"会话已复制到:\n{dst}")
            else:
                shutil.move(str(src), str(dst))
                messagebox.showinfo("完成", f"会话已移动到:\n{dst}")

            self._load_sessions()
        except Exception as e:
            messagebox.showerror("错误", f"迁移失败:\n{e}")


def main():
    root = tk.Tk()
    app = ClaudeSessionMigrator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
