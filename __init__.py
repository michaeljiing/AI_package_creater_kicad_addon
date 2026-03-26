"""
KiCad Footprint Generator Plugin
用于从数据手册自动生成封装的插件
"""
from urllib.parse import urlencode

import pcbnew
import wx
import wx.grid
import os
import json
import requests

class FootprintGeneratorPlugin(pcbnew.ActionPlugin):
    """
    KiCad 封装生成插件主类
    """

    def defaults(self):
        """
        插件的基本信息
        """
        self.name = "Footprint Generator"
        self.category = "Manufacturing"
        self.description = "从数据手册自动生成封装"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        if not hasattr(self, 'dialog') or self.dialog is None:
            self.dialog = GeneratorDialog(None)
            # 绑定窗口关闭事件，以便清理引用
            self.dialog.Bind(wx.EVT_CLOSE, self.on_dialog_close)
            self.dialog.Show()
        else:
            # 如果对话框已存在，将其带到前台
            self.dialog.Raise()
            self.dialog.SetFocus()

    def on_dialog_close(self, event):
        """对话框关闭时的处理"""
        self.dialog.Destroy()
        self.dialog = None


class GeneratorDialog(wx.Dialog):
    """
    AI封装生成器对话框
    """

    def __init__(self, parent):
        wx.Dialog.__init__(self, parent, title="AI封装生成器", size=(1400, 900),
                           style=wx.CAPTION |
                                 wx.CLOSE_BOX |
                                 wx.SYSTEM_MENU |
                                 wx.MINIMIZE_BOX |
                                 wx.FRAME_NO_TASKBAR
                           )

        self.api_base_url = "http://localhost:8080/api/packages"
        self.datasheet_uuid = None
        self.package_list = []  # 存储所有封装数据
        self.pdf_path = None
        self.current_page = 1
        self.total_pages = 1
        self.zoom_level = 100

        # 自动刷新相关变量
        self.auto_fetch_timer = None
        self.fetch_start_time = None
        self.fetch_timeout = 300  # 5分钟超时（秒）
        self.fetch_interval = 3  # 每3秒查询一次
        self.fetch_retry_count = 0
        self.max_retries = 100  # 5分钟 / 3秒 = 100次

        self.init_ui()
        self.Centre()
        # 绑定关闭事件
        self.Bind(wx.EVT_CLOSE, self.on_dialog_close)

    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局：水平分割
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # 左侧面板：PDF预览
        left_panel = self.create_left_panel()
        main_sizer.Add(left_panel, 1, wx.EXPAND | wx.ALL, 5)

        # 右侧面板：参数编辑
        right_panel = self.create_right_panel()
        main_sizer.Add(right_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(main_sizer)

    def create_left_panel(self):
        """
        创建左侧PDF预览面板 - 使用高质量PyMuPDF渲染
        """
        panel = wx.Panel(self)
        panel.SetMinSize((400, -1))
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 工具栏
        toolbar_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.upload_btn = wx.Button(panel, label="📂 上传PDF")
        self.upload_btn.Bind(wx.EVT_BUTTON, self.on_upload_pdf)
        toolbar_sizer.Add(self.upload_btn, 0, wx.ALL, 5)

        self.fetch_btn = wx.Button(panel, label="获取解析结果")
        self.fetch_btn.Bind(wx.EVT_BUTTON, self.on_fetch_results)
        self.fetch_btn.Enable(False)
        toolbar_sizer.Add(self.fetch_btn, 0, wx.ALL, 5)

        toolbar_sizer.AddSpacer(20)

        # 缩放控制
        toolbar_sizer.Add(wx.StaticText(panel, label="缩放:"), 0,
                          wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.zoom_out_btn = wx.Button(panel, label="➖", size=(35, -1))
        self.zoom_out_btn.Bind(wx.EVT_BUTTON, self.on_zoom_out)
        self.zoom_out_btn.Enable(False)
        toolbar_sizer.Add(self.zoom_out_btn, 0, wx.ALL, 5)

        self.zoom_label = wx.StaticText(panel, label="100%", size=(50, -1),
                                        style=wx.ALIGN_CENTER)
        toolbar_sizer.Add(self.zoom_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.zoom_in_btn = wx.Button(panel, label="➕", size=(35, -1))
        self.zoom_in_btn.Bind(wx.EVT_BUTTON, self.on_zoom_in)
        self.zoom_in_btn.Enable(False)
        toolbar_sizer.Add(self.zoom_in_btn, 0, wx.ALL, 5)

        self.reset_zoom_btn = wx.Button(panel, label="重置", size=(60, -1))
        self.reset_zoom_btn.Bind(wx.EVT_BUTTON, self.on_reset_zoom)
        self.reset_zoom_btn.Enable(False)
        toolbar_sizer.Add(self.reset_zoom_btn, 0, wx.ALL, 5)

        toolbar_sizer.AddStretchSpacer(1)

        sizer.Add(toolbar_sizer, 0, wx.EXPAND)

        # PDF显示区域 - 使用ScrolledPanel
        import wx.lib.scrolledpanel as scrolled
        self.pdf_scroll = scrolled.ScrolledPanel(panel, style=wx.SUNKEN_BORDER)
        self.pdf_scroll.SetBackgroundColour(wx.Colour(100, 100, 100))
        self.pdf_scroll.SetupScrolling()
        self.pdf_scroll.SetScrollRate(20, 20)

        # 图片面板（用于显示PDF页面）
        self.image_panel = wx.Panel(self.pdf_scroll)
        self.image_panel.SetBackgroundColour(wx.WHITE)

        # 使用BoxSizer将图片面板居中
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)
        scroll_sizer.AddStretchSpacer(1)

        image_sizer = wx.BoxSizer(wx.HORIZONTAL)
        image_sizer.AddStretchSpacer(1)
        image_sizer.Add(self.image_panel, 0, wx.ALIGN_CENTER)
        image_sizer.AddStretchSpacer(1)

        scroll_sizer.Add(image_sizer, 0, wx.EXPAND)
        scroll_sizer.AddStretchSpacer(1)

        self.pdf_scroll.SetSizer(scroll_sizer)

        # 显示默认提示
        self.show_placeholder("请上传PDF数据手册")

        sizer.Add(self.pdf_scroll, 1, wx.EXPAND | wx.ALL, 5)

        # 绑定鼠标滚轮事件
        self.pdf_scroll.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)
        self.image_panel.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)

        # 页面控制栏
        page_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.prev_page_btn = wx.Button(panel, label="◀ 上一页")
        self.prev_page_btn.Bind(wx.EVT_BUTTON, self.on_prev_page)
        self.prev_page_btn.Enable(False)
        page_sizer.Add(self.prev_page_btn, 0, wx.ALL, 5)

        page_sizer.Add(wx.StaticText(panel, label="页码:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.page_input = wx.TextCtrl(panel, size=(60, -1), style=wx.TE_PROCESS_ENTER)
        self.page_input.Bind(wx.EVT_TEXT_ENTER, self.on_page_jump)
        self.page_input.Enable(False)
        page_sizer.Add(self.page_input, 0, wx.ALL, 5)

        self.page_label = wx.StaticText(panel, label="/ 0")
        page_sizer.Add(self.page_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.next_page_btn = wx.Button(panel, label="下一页 ▶")
        self.next_page_btn.Bind(wx.EVT_BUTTON, self.on_next_page)
        self.next_page_btn.Enable(False)
        page_sizer.Add(self.next_page_btn, 0, wx.ALL, 5)

        self.jump_btn = wx.Button(panel, label="跳转")
        self.jump_btn.Bind(wx.EVT_BUTTON, self.on_page_jump)
        self.jump_btn.Enable(False)
        page_sizer.Add(self.jump_btn, 0, wx.ALL, 5)

        sizer.Add(page_sizer, 0, wx.EXPAND)

        # 文件名显示
        self.file_label = wx.StaticText(panel, label="📄 未选择文件", style=wx.ST_ELLIPSIZE_END)
        page_sizer.Add(self.file_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        # 状态栏
        self.status_text = wx.StaticText(panel, label="就绪")
        sizer.Add(self.status_text, 0, wx.EXPAND | wx.ALL, 5)

        panel.SetSizer(sizer)
        return panel

    def show_placeholder(self, text):
        """显示占位提示"""
        self.image_panel.DestroyChildren()

        # 创建一个简单的提示文本
        placeholder = wx.StaticText(self.image_panel, label=text)
        placeholder.SetForegroundColour(wx.Colour(150, 150, 150))
        font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        placeholder.SetFont(font)

        self.image_panel.SetSize((400, 300))
        self.image_panel.Layout()
        self.pdf_scroll.Layout()

    def create_placeholder_bitmap(self, width, height, text):
        """
        创建占位图片
        """
        bitmap = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bitmap)

        # 填充背景
        dc.SetBackground(wx.Brush(wx.Colour(240, 240, 240)))
        dc.Clear()

        # 绘制文本
        dc.SetTextForeground(wx.Colour(100, 100, 100))
        font = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        dc.SetFont(font)

        text_width, text_height = dc.GetTextExtent(text)
        dc.DrawText(text, (width - text_width) // 2, (height - text_height) // 2)

        dc.SelectObject(wx.NullBitmap)
        return bitmap

    def load_pdf_preview(self):
        """
        加载PDF预览 - 使用高质量PyMuPDF渲染
        """
        if not self.pdf_path:
            return

        try:
            import fitz
            from PIL import Image

            # 关闭之前的文档
            if hasattr(self, 'pdf_doc') and self.pdf_doc:
                self.pdf_doc.close()

            # 打开PDF文档
            self.pdf_doc = fitz.open(self.pdf_path)
            self.total_pages = len(self.pdf_doc)
            self.current_page = 1  # 从1开始
            self.zoom_level = 50  # 默认90%
            self.render_dpi = 150  # 高质量渲染DPI

            # 启用所有控制按钮
            self.prev_page_btn.Enable(True)
            self.next_page_btn.Enable(True)
            self.page_input.Enable(True)
            self.jump_btn.Enable(True)
            self.zoom_in_btn.Enable(True)
            self.zoom_out_btn.Enable(True)
            self.reset_zoom_btn.Enable(True)

            # 更新文件名显示
            filename = os.path.basename(self.pdf_path)
            self.file_label.SetLabel(f"📄 {filename}")

            # 渲染第一页
            self.render_pdf_page()

            self.set_status(f"已加载: {filename} ({self.total_pages} 页)")

        except ImportError:
            self.show_placeholder("需要安装 PyMuPDF\n\npip install PyMuPDF")
            self.set_status("请安装 PyMuPDF: pip install PyMuPDF")
            wx.MessageBox("需要安装 PyMuPDF 来预览PDF\n\n运行命令: pip install PyMuPDF",
                          "提示", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            self.show_placeholder(f"PDF加载失败\n\n{str(e)}")
            self.set_status(f"PDF加载失败: {str(e)}")

    def render_pdf_page(self):
        """
        渲染PDF页面 - 高质量显示
        """
        if not hasattr(self, 'pdf_doc') or not self.pdf_doc:
            return

        try:
            import fitz
            from PIL import Image

            # 获取当前页（转换为0-based索引）
            page = self.pdf_doc.load_page(self.current_page - 1)

            # 计算缩放因子
            zoom_factor = (self.zoom_level / 100.0) * (self.render_dpi / 72.0)
            mat = fitz.Matrix(zoom_factor, zoom_factor)

            # 渲染为高质量图像
            pix = page.get_pixmap(matrix=mat, alpha=False)

            # 转换为PIL Image
            img_data = pix.samples
            img = Image.frombytes("RGB", [pix.width, pix.height], img_data)

            # 可选：轻微锐化提高清晰度
            if self.render_dpi >= 200:
                from PIL import ImageFilter
                img = img.filter(ImageFilter.SHARPEN)

            # 转换为wx.Bitmap
            width, height = img.size
            img_wx = wx.Bitmap.FromBuffer(width, height, img.tobytes())

            # 清除之前的图片
            self.image_panel.DestroyChildren()

            # 创建StaticBitmap显示
            static_bitmap = wx.StaticBitmap(self.image_panel, bitmap=img_wx)
            static_bitmap.SetPosition((0, 0))

            # 设置面板大小
            self.image_panel.SetSize((width, height))
            self.image_panel.SetMinSize((width, height))

            # 更新虚拟大小
            self.pdf_scroll.SetVirtualSize((width + 20, height + 20))

            # 更新显示
            zoom_percent = int(self.zoom_level)
            self.zoom_label.SetLabel(f"{zoom_percent}%")

            # 更新页码
            self.page_label.SetLabel(f"/ {self.total_pages}")
            self.page_input.SetValue(str(self.current_page))

            # 刷新布局
            self.pdf_scroll.Layout()
            self.pdf_scroll.Scroll(0, 0)
            self.image_panel.Refresh()
            self.pdf_scroll.Refresh()

        except Exception as e:
            print(f"渲染PDF错误: {e}")
            self.show_placeholder(f"渲染失败\n\n{str(e)}")

    def on_prev_page(self, event):
        """上一页"""
        if hasattr(self, 'pdf_doc') and self.pdf_doc and self.current_page > 1:
            self.current_page -= 1
            self.render_pdf_page()

    def on_next_page(self, event):
        """下一页"""
        if hasattr(self, 'pdf_doc') and self.pdf_doc and self.current_page < self.total_pages:
            self.current_page += 1
            self.render_pdf_page()

    def on_page_jump(self, event):
        """跳转到指定页"""
        if not hasattr(self, 'pdf_doc') or not self.pdf_doc:
            return

        try:
            page_text = self.page_input.GetValue()
            if not page_text:
                return

            page_num = int(page_text)

            if 1 <= page_num <= self.total_pages:
                self.current_page = page_num
                self.render_pdf_page()
            else:
                wx.MessageBox(f"页码必须在 1 到 {self.total_pages} 之间",
                              "警告", wx.OK | wx.ICON_WARNING)
        except ValueError:
            wx.MessageBox("请输入有效的页码", "警告", wx.OK | wx.ICON_WARNING)

    def on_zoom_in(self, event):
        """放大"""
        if hasattr(self, 'pdf_doc') and self.pdf_doc and self.zoom_level < 200:
            self.zoom_level += 10
            self.render_pdf_page()

    def on_zoom_out(self, event):
        """缩小"""
        if hasattr(self, 'pdf_doc') and self.pdf_doc and self.zoom_level > 50:
            self.zoom_level -= 10
            self.render_pdf_page()

    def on_reset_zoom(self, event):
        """重置缩放"""
        if hasattr(self, 'pdf_doc') and self.pdf_doc:
            self.zoom_level = 100
            self.render_pdf_page()

    def on_mouse_wheel(self, event):
        """处理鼠标滚轮事件"""
        if not hasattr(self, 'pdf_doc') or not self.pdf_doc:
            event.Skip()
            return

        rotation = event.GetWheelRotation()

        # Ctrl + 滚轮进行缩放
        if event.ControlDown():
            if rotation > 0:
                self.on_zoom_in(event)
            else:
                self.on_zoom_out(event)
        # 普通滚轮进行垂直滚动
        else:
            if rotation > 0:
                self.pdf_scroll.ScrollLines(-3)
            else:
                self.pdf_scroll.ScrollLines(3)

        event.Skip()

    def on_jump_to_page(self, event, page_ctrl):
        """
        从封装表格跳转到指定页码
        """
        page_numbers = page_ctrl.GetValue()
        if not page_numbers:
            return

        try:
            # 解析页码
            if ',' in page_numbers:
                first_page = int(page_numbers.split(',')[0].strip())
            elif '-' in page_numbers:
                first_page = int(page_numbers.split('-')[0].strip())
            else:
                first_page = int(page_numbers.strip())

            # 跳转
            if hasattr(self, 'pdf_doc') and self.pdf_doc:
                if 1 <= first_page <= self.total_pages:
                    self.current_page = first_page
                    self.page_input.SetValue(str(first_page))
                    self.render_pdf_page()
                    self.set_status(f"已跳转到第 {first_page} 页")
                else:
                    wx.MessageBox(f"页码 {first_page} 超出范围 (1-{self.total_pages})",
                                  "提示", wx.OK | wx.ICON_WARNING)
            else:
                wx.MessageBox("PDF未加载", "提示", wx.OK | wx.ICON_INFORMATION)

        except ValueError:
            wx.MessageBox(f"无法解析页码: {page_numbers}", "错误", wx.OK | wx.ICON_ERROR)

    def on_fit_width(self, event):
        """适应宽度"""
        if not hasattr(self, 'pdf_doc') or not self.pdf_doc:
            return

        try:
            import fitz

            # 获取当前页和可视区域宽度
            page = self.pdf_doc[self.current_page - 1]
            page_width = page.rect.width
            visible_width = self.pdf_scroll.GetClientSize().width - 40  # 减去边距

            # 计算合适的缩放级别
            self.zoom_level = int((visible_width / page_width) * 100)
            self.zoom_level = max(50, min(200, self.zoom_level))  # 限制在50-200之间

            self.zoom_label.SetLabel(f"{self.zoom_level}%")
            self.render_pdf_page()

        except Exception as e:
            print(f"适应宽度错误: {e}")

    def update_page_label(self):
        """更新页码标签"""
        self.page_label.SetLabel(f"页码: {self.current_page}/{self.total_pages}")
        self.page_input.SetValue(self.current_page)

    def create_right_panel(self):
        """
        创建右侧参数编辑面板
        """
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 标题
        title = wx.StaticText(panel, label="封装参数解析结果")
        title_font = title.GetFont()
        title_font.PointSize += 2
        title_font = title_font.Bold()
        title.SetFont(title_font)
        sizer.Add(title, 0, wx.ALL, 10)

        # 滚动窗口，用于容纳多个封装表格
        self.scroll_window = wx.ScrolledWindow(panel, style=wx.VSCROLL)
        self.scroll_window.SetScrollRate(0, 20)

        self.scroll_sizer = wx.BoxSizer(wx.VERTICAL)
        self.scroll_window.SetSizer(self.scroll_sizer)

        sizer.Add(self.scroll_window, 1, wx.EXPAND | wx.ALL, 5)

        # 底部操作按钮
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        btn_sizer.AddStretchSpacer()

        self.save_generate_btn = wx.Button(panel, label="保存并生成所有封装")
        self.save_generate_btn.Bind(wx.EVT_BUTTON, self.on_save_and_generate_all)
        self.save_generate_btn.Enable(False)
        btn_sizer.Add(self.save_generate_btn, 0, wx.ALL, 5)

        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)

        panel.SetSizer(sizer)
        return panel

    def on_upload_pdf(self, event):
        """
        上传PDF处理 - 保留原有的API上传功能
        """
        wildcard = "PDF文件 (*.pdf)|*.pdf"
        dialog = wx.FileDialog(self, "选择PDF数据手册", wildcard=wildcard,
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)

        if dialog.ShowModal() == wx.ID_OK:
            self.pdf_path = dialog.GetPath()

            # 清空右侧表格和数据
            self.clear_package_data()

            # 先加载PDF预览
            self.load_pdf_preview()

            # 然后上传到API
            self.upload_pdf_to_api()

        dialog.Destroy()

    def upload_pdf_to_api(self):
        """
        上传PDF到API
        """
        if not self.pdf_path:
            return

        self.set_status("正在上传数据手册...")

        try:
            with open(self.pdf_path, 'rb') as f:
                filename = os.path.basename(f.name)
                files = {'file': (filename, f, 'application/pdf')}
                response = requests.post(self.api_base_url + "/upload", files=files, timeout=60)

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    self.datasheet_uuid = result.get('uuid')
                    file_id = result.get('fileId')
                    self.set_status(f"上传成功！UUID: {self.datasheet_uuid}, FileID: {file_id}")
                    # 显示正在解析中的状态
                    self.show_parsing_status()
                    # 启用获取按钮
                    self.fetch_btn.Enable(True)

                    # 自动获取解析结果
                    wx.CallLater(1000, self.start_auto_fetch)
                else:
                    self.set_status(f"上传失败: {result.get('message', '未知错误')}")
                    wx.MessageBox(f"上传失败: {result.get('message', '未知错误')}",
                                "错误", wx.OK | wx.ICON_ERROR)
            else:
                self.set_status(f"上传失败: HTTP {response.status_code}")
                wx.MessageBox(f"上传失败: {response.text}", "错误", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            self.set_status(f"上传错误: {str(e)}")
            wx.MessageBox(f"上传错误: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def on_fetch_results(self, event):
        """
        获取解析结果按钮处理
        """
        self.fetch_package_data()

    def fetch_package_data(self):
        """
        从API获取封装数据
        """
        if not self.datasheet_uuid:
            wx.MessageBox("请先上传数据手册", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        # 停止之前的自动刷新
        self.stop_auto_fetch()
        # 开始新的自动刷新
        self.start_auto_fetch()
        self.set_status("正在获取封装参数...")
        try:
            url = f"{self.api_base_url}/{self.datasheet_uuid}"
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                self.package_list = response.json()
                # 停止解析动画
                self.stop_parsing_animation()

                if self.package_list and len(self.package_list) > 0:
                    self.display_all_packages()
                    self.set_status(f"成功获取 {len(self.package_list)} 个封装结果")
                    self.save_generate_btn.Enable(True)
                else:
                    self.set_status("正在解析，请稍后。。。")
            else:
                # 停止解析动画
                self.stop_parsing_animation()
                self.set_status(f"获取失败: HTTP {response.status_code}")

                # 显示错误信息
                self.scroll_sizer.Clear(True)
                error_panel = wx.Panel(self.scroll_window)
                error_sizer = wx.BoxSizer(wx.VERTICAL)

                error_text = wx.StaticText(error_panel,
                                          label=f"❌ 获取失败\n\n{response.text}")
                error_text.SetForegroundColour(wx.Colour(200, 50, 50))
                error_sizer.Add(error_text, 0, wx.ALIGN_CENTER | wx.ALL, 20)

                error_panel.SetSizer(error_sizer)
                self.scroll_sizer.Add(error_panel, 1, wx.EXPAND | wx.ALL, 10)
                self.scroll_window.Layout()

        except Exception as e:
            self.set_status(f"获取错误: {str(e)}")
            wx.MessageBox(f"获取错误: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def display_all_packages(self):
        """
        显示所有封装的参数表格
        """
        # 清空现有内容
        self.scroll_sizer.Clear(True)

        # 为每个封装创建一个表格面板
        for idx, package in enumerate(self.package_list):
            panel = self.create_package_panel(package, idx)
            self.scroll_sizer.Add(panel, 0, wx.EXPAND | wx.ALL, 10)

            # 添加分隔线
            if idx < len(self.package_list) - 1:
                line = wx.StaticLine(self.scroll_window, style=wx.LI_HORIZONTAL)
                self.scroll_sizer.Add(line, 0, wx.EXPAND | wx.ALL, 5)

        self.scroll_window.Layout()
        self.scroll_sizer.Layout()
        self.scroll_window.FitInside()

    def clear_package_data(self):
        """
        清空右侧封装数据和表格
        """
        # 清空数据
        self.package_list = []
        self.datasheet_uuid = None

        # 清空右侧滚动区域的所有内容
        self.scroll_sizer.Clear(True)

        # 添加提示信息
        hint_panel = wx.Panel(self.scroll_window)
        hint_sizer = wx.BoxSizer(wx.VERTICAL)

        hint_text = wx.StaticText(hint_panel,
                                 label="请上传PDF并等待解析结果")
        hint_text.SetForegroundColour(wx.Colour(150, 150, 150))
        font = wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL)
        hint_text.SetFont(font)

        hint_sizer.AddStretchSpacer(1)
        hint_sizer.Add(hint_text, 0, wx.ALIGN_CENTER | wx.ALL, 20)
        hint_sizer.AddStretchSpacer(1)

        hint_panel.SetSizer(hint_sizer)
        self.scroll_sizer.Add(hint_panel, 1, wx.EXPAND | wx.ALL, 10)

        # 刷新布局
        self.scroll_window.Layout()
        self.scroll_sizer.Layout()
        self.scroll_window.FitInside()

        # 禁用保存按钮
        self.save_generate_btn.Enable(False)

        # 重置获取按钮状态
        self.fetch_btn.Enable(False)

    def show_parsing_status(self, show_retry_button=False):
        """
        显示正在解析中的状态

        Args:
            show_retry_button: 是否显示手动重试按钮
        """
        # 清空右侧滚动区域的所有内容
        self.scroll_sizer.Clear(True)

        # 创建状态面板
        status_panel = wx.Panel(self.scroll_window)
        status_panel.SetBackgroundColour(wx.Colour(250, 250, 250))
        status_sizer = wx.BoxSizer(wx.VERTICAL)

        status_sizer.AddStretchSpacer(1)

        if show_retry_button:
            # 超时后显示
            title_text = wx.StaticText(status_panel, label="⏱️ 解析超时")
            title_font = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
            title_text.SetFont(title_font)
            title_text.SetForegroundColour(wx.Colour(200, 100, 50))
            status_sizer.Add(title_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)

            hint_text = wx.StaticText(status_panel,
                                      label="解析时间超过5分钟\n可能PDF较大或服务器繁忙\n请手动点击下方按钮重新获取")
            hint_text.SetForegroundColour(wx.Colour(100, 100, 100))
            hint_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
            hint_text.SetFont(hint_font)
            status_sizer.Add(hint_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)

            # 手动重试按钮
            retry_btn = wx.Button(status_panel, label="🔄 重新获取解析结果", size=(200, 40))
            retry_btn.SetBackgroundColour(wx.Colour(74, 134, 232))
            retry_btn.SetForegroundColour(wx.WHITE)
            retry_font = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
            retry_btn.SetFont(retry_font)
            retry_btn.Bind(wx.EVT_BUTTON, lambda e: self.start_auto_fetch())
            status_sizer.Add(retry_btn, 0, wx.ALIGN_CENTER | wx.ALL, 20)

        else:
            # 正在解析中显示
            title_text = wx.StaticText(status_panel, label="⏳ 正在解析中，请稍后...")
            title_font = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
            title_text.SetFont(title_font)
            title_text.SetForegroundColour(wx.Colour(70, 130, 180))
            status_sizer.Add(title_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)

            hint_text = wx.StaticText(status_panel,
                                      label="正在从PDF中提取封装参数\n系统会自动刷新结果（最多5分钟）")
            hint_text.SetForegroundColour(wx.Colour(100, 100, 100))
            hint_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL)
            hint_text.SetFont(hint_font)
            status_sizer.Add(hint_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)

            # 动画点点点
            self.parsing_dots = 0
            self.parsing_text = wx.StaticText(status_panel, label="...")
            parsing_font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
            self.parsing_text.SetFont(parsing_font)
            self.parsing_text.SetForegroundColour(wx.Colour(70, 130, 180))
            status_sizer.Add(self.parsing_text, 0, wx.ALIGN_CENTER | wx.ALL, 5)

            # 显示已等待时间
            self.wait_time_text = wx.StaticText(status_panel, label="已等待: 0秒")
            wait_font = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
            self.wait_time_text.SetFont(wait_font)
            self.wait_time_text.SetForegroundColour(wx.Colour(150, 150, 150))
            status_sizer.Add(self.wait_time_text, 0, wx.ALIGN_CENTER | wx.ALL, 5)

            # 启动动画定时器
            if not hasattr(self, 'parsing_timer'):
                self.parsing_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.on_parsing_animation, self.parsing_timer)
            self.parsing_timer.Start(500)  # 每500毫秒更新一次

        status_sizer.AddStretchSpacer(1)

        status_panel.SetSizer(status_sizer)
        self.scroll_sizer.Add(status_panel, 1, wx.EXPAND | wx.ALL, 10)

        # 刷新布局
        self.scroll_window.Layout()
        self.scroll_sizer.Layout()
        self.scroll_window.FitInside()

    def on_parsing_animation(self, event):
        """
        解析动画效果，同时更新等待时间
        """
        if hasattr(self, 'parsing_text') and self.parsing_text:
            self.parsing_dots = (self.parsing_dots + 1) % 4
            dots = "." * (self.parsing_dots + 1)
            self.parsing_text.SetLabel(dots)

        # 更新等待时间
        if hasattr(self, 'wait_time_text') and self.wait_time_text and self.fetch_start_time:
            import time
            elapsed = int(time.time() - self.fetch_start_time)
            self.wait_time_text.SetLabel(f"已等待: {elapsed}秒 / 300秒")

    def stop_parsing_animation(self):
        """
        停止解析动画
        """
        if hasattr(self, 'parsing_timer') and self.parsing_timer and self.parsing_timer.IsRunning():
            self.parsing_timer.Stop()
        if hasattr(self, 'parsing_text'):
            self.parsing_text = None
        if hasattr(self, 'wait_time_text'):
            self.wait_time_text = None

    def on_dialog_close(self, event):
        """
        对话框关闭时清理资源
        """
        # 停止所有定时器
        self.stop_auto_fetch()
        self.stop_parsing_animation()

        # 关闭PDF文档
        if hasattr(self, 'pdf_doc') and self.pdf_doc:
            self.pdf_doc.close()

        # 继续关闭
        event.Skip()

    def start_auto_fetch(self):
        """
        开始自动刷新解析结果
        """
        import time

        # 记录开始时间
        self.fetch_start_time = time.time()
        self.fetch_retry_count = 0

        # 显示解析中状态
        self.show_parsing_status(show_retry_button=False)

        # 立即获取一次
        self.auto_fetch_package_data()

    def auto_fetch_package_data(self):
        """
        自动获取封装数据（带超时控制）
        """
        import time

        if not self.datasheet_uuid:
            return

        # 检查是否超时
        elapsed = time.time() - self.fetch_start_time
        if elapsed > self.fetch_timeout:
            # 超时，停止自动刷新
            self.stop_auto_fetch()
            self.show_parsing_status(show_retry_button=True)
            self.set_status("解析超时（5分钟），请手动重试")
            return

        # 更新状态
        self.set_status(f"正在获取封装参数... (第 {self.fetch_retry_count + 1} 次尝试)")

        try:
            url = f"{self.api_base_url}/{self.datasheet_uuid}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                self.package_list = response.json()

                if self.package_list and len(self.package_list) > 0:
                    # 获取到数据，停止自动刷新
                    self.stop_auto_fetch()
                    self.stop_parsing_animation()

                    # 显示封装表格
                    self.display_all_packages()
                    self.set_status(f"成功获取 {len(self.package_list)} 个封装结果")
                    self.save_generate_btn.Enable(True)
                else:
                    # 没有数据，继续轮询
                    self.fetch_retry_count += 1

                    # 启动定时器，间隔后再次查询
                    if not self.auto_fetch_timer:
                        self.auto_fetch_timer = wx.Timer(self)
                        self.Bind(wx.EVT_TIMER, self.on_auto_fetch_timer, self.auto_fetch_timer)

                    self.auto_fetch_timer.Start(self.fetch_interval * 1000, wx.TIMER_ONE_SHOT)
            else:
                # 请求失败，继续重试
                self.fetch_retry_count += 1

                if not self.auto_fetch_timer:
                    self.auto_fetch_timer = wx.Timer(self)
                    self.Bind(wx.EVT_TIMER, self.on_auto_fetch_timer, self.auto_fetch_timer)

                self.auto_fetch_timer.Start(self.fetch_interval * 1000, wx.TIMER_ONE_SHOT)

        except Exception as e:
            # 发生错误，继续重试
            print(f"自动获取错误: {str(e)}")
            self.fetch_retry_count += 1

            if not self.auto_fetch_timer:
                self.auto_fetch_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.on_auto_fetch_timer, self.auto_fetch_timer)

            self.auto_fetch_timer.Start(self.fetch_interval * 1000, wx.TIMER_ONE_SHOT)

    def on_auto_fetch_timer(self, event):
        """
        定时器触发，继续获取数据
        """
        self.auto_fetch_package_data()

    def stop_auto_fetch(self):
        """
        停止自动刷新
        """
        if self.auto_fetch_timer and self.auto_fetch_timer.IsRunning():
            self.auto_fetch_timer.Stop()

        self.fetch_start_time = None
        self.fetch_retry_count = 0

    def create_package_panel(self, package, index):
        """
        为单个封装创建编辑面板
        """
        panel = wx.Panel(self.scroll_window)
        panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 封装基本信息（可编辑）
        info_sizer = wx.FlexGridSizer(3, 3, 5, 10)
        info_sizer.AddGrowableCol(1)

        # 封装类型
        info_sizer.Add(wx.StaticText(panel, label="封装类型:"), 0,
                      wx.ALIGN_CENTER_VERTICAL)
        package_type_ctrl = wx.TextCtrl(panel, value=package.get('packageType', ''))
        package_type_ctrl.SetName(f"packageType_{index}")
        info_sizer.Add(package_type_ctrl, 1, wx.EXPAND)
        info_sizer.AddSpacer(1)

        # 封装名称
        info_sizer.Add(wx.StaticText(panel, label="封装名称:"), 0,
                      wx.ALIGN_CENTER_VERTICAL)
        package_name_ctrl = wx.TextCtrl(panel, value=package.get('packageName', ''))
        package_name_ctrl.SetName(f"packageName_{index}")
        info_sizer.Add(package_name_ctrl, 1, wx.EXPAND)
        info_sizer.AddSpacer(1)

        # 页码 + 跳转按钮
        info_sizer.Add(wx.StaticText(panel, label="页码:"), 0,
                      wx.ALIGN_CENTER_VERTICAL)
        page_numbers_ctrl = wx.TextCtrl(panel, value=package.get('pageNumbers', ''))
        page_numbers_ctrl.SetName(f"pageNumbers_{index}")
        info_sizer.Add(page_numbers_ctrl, 1, wx.EXPAND)

        # 跳转按钮
        jump_btn = wx.Button(panel, label="跳转", size=(60, -1))
        jump_btn.Bind(wx.EVT_BUTTON,
                     lambda e, ctrl=page_numbers_ctrl: self.on_jump_to_page(e, ctrl))
        info_sizer.Add(jump_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        sizer.Add(info_sizer, 0, wx.EXPAND | wx.ALL, 10)


        # 参数表格
        params_grid = wx.grid.Grid(panel)
        params_grid.SetName(f"params_{index}")
        params_grid.CreateGrid(0, 3)  # 初始0行，3列
        params_grid.SetColLabelValue(0, "参数名称")
        params_grid.SetColLabelValue(1, "数值")
        params_grid.SetColLabelValue(2, "单位")

        params_grid.SetRowLabelSize(0)

        # 设置列宽
        params_grid.SetColSize(0, 330)
        params_grid.SetColSize(1, 180)
        params_grid.SetColSize(2, 100)

        # 设置表格高度
        params_grid.SetMinSize((-1, 300))

        params_grid.SetDefaultEditor(wx.grid.GridCellTextEditor())
        params_grid.EnableEditing(True)

        # 解析并填充参数
        package_result = package.get('packageResult', '{}')
        try:
            params = json.loads(package_result)

            row_idx = 0
            for key, value in params.items():
                params_grid.AppendRows(1)

                # 设置参数名称（只读）
                params_grid.SetCellValue(row_idx, 0, key)
                params_grid.SetReadOnly(row_idx, 0, True)
                params_grid.SetCellBackgroundColour(row_idx, 0, wx.Colour(240, 240, 240))

                # 设置数值（可编辑）
                params_grid.SetCellValue(row_idx, 1, str(value))
                params_grid.SetCellBackgroundColour(row_idx, 1, wx.WHITE)
                params_grid.SetCellEditor(row_idx, 1, wx.grid.GridCellTextEditor())
                params_grid.SetReadOnly(row_idx, 1, False)

                # 设置单位（只读）
                unit = self.get_unit_for_param(key)
                params_grid.SetCellValue(row_idx, 2, unit)
                params_grid.SetReadOnly(row_idx, 2, True)
                params_grid.SetCellBackgroundColour(row_idx, 2, wx.Colour(240, 240, 240))

                row_idx += 1

        except Exception as e:
            print(f"解析封装参数失败: {str(e)}")

        # 自动调整行高
        params_grid.AutoSizeRows()

        # 禁用行列标签的拖拽调整
        params_grid.EnableDragColSize(False)
        params_grid.EnableDragRowSize(False)
        params_grid.EnableDragGridSize(False)

        sizer.Add(params_grid, 1, wx.EXPAND | wx.ALL, 10)

        # 操作按钮
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        add_param_btn = wx.Button(panel, label="添加参数")
        add_param_btn.Bind(wx.EVT_BUTTON,
                           lambda e, pg=params_grid: self.on_add_param_grid(e, pg))
        btn_sizer.Add(add_param_btn, 0, wx.ALL, 5)

        del_param_btn = wx.Button(panel, label="删除选中参数")
        del_param_btn.Bind(wx.EVT_BUTTON,
                           lambda e, pg=params_grid: self.on_delete_param_grid(e, pg))
        btn_sizer.Add(del_param_btn, 0, wx.ALL, 5)

        btn_sizer.AddStretchSpacer()

        generate_btn = wx.Button(panel, label="生成此封装")
        generate_btn.Bind(wx.EVT_BUTTON,
                          lambda e, i=index: self.on_generate_single(e, i))
        btn_sizer.Add(generate_btn, 0, wx.ALL, 5)

        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)

        panel.SetSizer(sizer)
        return panel

    def get_unit_for_param(self, param_name):
        """
        根据参数名称返回单位
        """
        param_lower = param_name.lower()
        if any(x in param_lower for x in ['count', 'orientation', 'direction', 'visual', 'index']):
            return ""
        else:
            return "mm"

    def on_add_param_grid(self, event, params_grid):
        """
        添加参数到Grid
        """
        # 创建自定义对话框
        dlg = AddParameterDialog(self)

        if dlg.ShowModal() == wx.ID_OK:
            param_name = dlg.param_name.GetValue()
            param_value = dlg.param_value.GetValue()
            param_unit = dlg.param_unit.GetValue()

            if param_name:  # 至少要有参数名
                # 添加新行
                params_grid.AppendRows(1)
                row_idx = params_grid.GetNumberRows() - 1

                # 设置参数名称（只读）
                params_grid.SetCellValue(row_idx, 0, param_name)
                params_grid.SetReadOnly(row_idx, 0, True)
                params_grid.SetCellBackgroundColour(row_idx, 0, wx.Colour(240, 240, 240))

                # 设置数值（可编辑）
                params_grid.SetCellValue(row_idx, 1, param_value)
                params_grid.SetCellBackgroundColour(row_idx, 1, wx.WHITE)

                # 设置单位（只读）
                params_grid.SetCellValue(row_idx, 2, param_unit)
                params_grid.SetReadOnly(row_idx, 2, True)
                params_grid.SetCellBackgroundColour(row_idx, 2, wx.Colour(240, 240, 240))

                # 刷新显示
                params_grid.ForceRefresh()

        dlg.Destroy()

    def on_delete_param_grid(self, event, params_grid):
        """
        删除Grid中选中的参数
        """
        # 获取当前选中的行
        selected_rows = params_grid.GetSelectedRows()

        if not selected_rows:
            # 如果没有选中整行，尝试获取当前单元格所在行
            current_row = params_grid.GetGridCursorRow()
            if current_row >= 0:
                selected_rows = [current_row]

        if selected_rows:
            # 从后往前删除（避免索引变化）
            for row in sorted(selected_rows, reverse=True):
                params_grid.DeleteRows(row, 1)

            params_grid.ForceRefresh()
        else:
            wx.MessageBox("请先选中要删除的行", "提示", wx.OK | wx.ICON_INFORMATION)

    def on_generate_single(self, event, index):
        """
        生成单个封装
        """
        package_data = self.collect_package_data(index)
        if package_data:
            self.generate_kicad_footprint(package_data)

    def on_save_and_generate_all(self, event):
        """
        保存所有封装参数并生成
        """
        self.set_status("正在保存所有封装参数...")

        success_count = 0
        for idx, package in enumerate(self.package_list):
            package_data = self.collect_package_data(idx)
            if package_data:
                # 保存到API
                if self.save_package_to_api(package_data):
                    success_count += 1
                    # 生成封装
                    self.generate_kicad_footprint(package_data)

        self.set_status(f"成功保存并生成 {success_count}/{len(self.package_list)} 个封装")
        wx.MessageBox(f"成功生成 {success_count} 个封装文件", "完成",
                     wx.OK | wx.ICON_INFORMATION)

    def collect_package_data(self, index):
        """
        收集指定索引的封装数据
        """
        try:
            # 查找对应的控件
            panel = self.scroll_sizer.GetItem(index * 2).GetWindow()  # *2是因为有分隔线

            # 收集基本信息
            package_type = panel.FindWindowByName(f"packageType_{index}").GetValue()
            package_name = panel.FindWindowByName(f"packageName_{index}").GetValue()
            page_numbers = panel.FindWindowByName(f"pageNumbers_{index}").GetValue()

            # 收集参数 - 从Grid中获取
            params_grid = panel.FindWindowByName(f"params_{index}")
            params = {}

            for row in range(params_grid.GetNumberRows()):
                key = params_grid.GetCellValue(row, 0)
                value = params_grid.GetCellValue(row, 1)
                if key:  # 只添加有名称的参数
                    params[key] = value

            package_id = self.package_list[index].get('packageId')
            return {
                'packageId': package_id,
                'packageType': package_type,
                'packageName': package_name,
                'pageNumbers': page_numbers,
                'packageResult': params
            }
        except Exception as e:
            print(f"收集封装数据失败: {str(e)}")
            return None

    def save_package_to_api(self, package_data):
        """
        保存封装数据到API
        """
        try:
            params = {
                'packageName': package_data['packageName'],
                'pageNumbers': package_data['pageNumbers']
            }
            package_id =  package_data['packageId']
            url = f"{self.api_base_url}/{package_id}?{urlencode(params)}"

            payload = {
                'packageResult': json.dumps(package_data['packageResult'])
            }

            response = requests.put(url, json=payload,
                                   headers={'Content-Type': 'application/json'},
                                   timeout=30)

            return response.status_code == 200
        except Exception as e:
            print(f"保存到API失败: {str(e)}")
            return False

    def generate_kicad_footprint(self, package_data):
        """
        生成KiCad封装文件
        """
        try:
            params = package_data['packageResult']
            package_name = package_data['packageName']
            package_type = package_data.get('packageType', '').upper()
            # 获取当前板子
            board = pcbnew.GetBoard()
            if not board:
                wx.MessageBox("无法获取当前板子", "错误", wx.OK | wx.ICON_ERROR)
                return

            if package_type == 'SOIC':
                footprint = self._generate_soic_footprint(package_name, params)
            elif package_type == 'QFN':
                footprint = self._generate_qfn_footprint(package_name, params)
            elif package_type == 'BGA':
                footprint = self._generate_bga_footprint(package_name, params)
            else:
                wx.MessageBox(f"不支持的封装类型: {package_type}", "错误", wx.OK | wx.ICON_ERROR)
                return

            # 添加到板子
            if footprint:
                board.Add(footprint)
                # 刷新显示
                pcbnew.Refresh()
                # 保存板子
                pcbnew.GetBoard().Save(board.GetFileName())
                self.save_package_to_api(package_data)
                wx.MessageBox(f"封装 {package_name} 已添加到板子", "成功", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            import traceback
            with open("C:/Log/kicad_plugin_error.txt", "w") as f:
                f.write(traceback.format_exc())
            wx.MessageBox(f"生成封装错误: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def _generate_soic_footprint(self, package_name, params):
        """
        生成SOIC封装
        """
        try:
            # 提取SOIC参数，同时检查是否为有效数值
            try:
                pin_count = int(params.get('Pin Count', params.get('PinCount', 0)))
                if pin_count <= 0:
                    raise ValueError("引脚数必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的引脚数参数")

            try:
                pitch = float(params.get('Pitch', 0))
                if pitch <= 0:
                    raise ValueError("间距必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的间距参数")

            try:
                #pad_width = float(params.get('Pad Width', 0))
                pad_width = self._get_soic_pad_width(pitch, params)
                if pad_width <= 0:
                    raise ValueError("焊盘宽度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的焊盘宽度参数")

            try:
                #pad_length = float(params.get('Pad Length', 0))
                pad_length = self._get_soic_pad_length(pitch, params)
                if pad_length <= 0:
                    raise ValueError("焊盘长度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的焊盘长度参数")

            try:
                overall_width = float(params.get('Overall Width', params.get('OverallWidth', 0)))
                if overall_width <= 0:
                    raise ValueError("总宽度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的总宽度参数")

            try:
                body_length = float(params.get('Package Body Length', params.get('PackageBodyLength', 0)))
                if body_length <= 0:
                    raise ValueError("封装体长度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的封装体长度参数")

            try:
                body_width = float(params.get('Package Body Width', params.get('PackageBodyWidth', 0)))
                if body_width <= 0:
                    raise ValueError("封装体宽度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的封装体宽度参数")

            # 验证引脚数为偶数
            if pin_count % 2 != 0:
                raise ValueError(f"SOIC封装引脚数必须是偶数，当前为{pin_count}")

            # 验证焊盘长度小于总宽度
            if pad_length >= overall_width:
                raise ValueError(f"焊盘长度({pad_length}mm)必须小于总宽度({overall_width}mm)")

            # 创建封装对象
            board = pcbnew.GetBoard()
            if not board:
                raise Exception("无法获取当前板子")
            footprint = pcbnew.FOOTPRINT(board)

            # 设置封装ID
            footprint.SetFPID(pcbnew.LIB_ID("", package_name))

            # 设置描述和关键字
            footprint.SetLibDescription(f"SOIC, {pin_count} Pin, pitch {pitch}mm")
            footprint.SetKeywords("SOIC SO")

            # 设置参考和值
            self._add_soic_reference(footprint, body_length)
            footprint.SetValue(package_name)
            self._add_soic_value(footprint, package_name, body_length)

            # 添加焊盘
            self._add_soic_pads(footprint, params)

            # 添加丝印层
            self._add_soic_silkscreen(footprint, params)

            # 添加禁止布线层（Courtyard）
            self._add_soic_courtyard(footprint, params)

            # 添加装配文档层
            self._add_soic_fab_layer(footprint, params)

            return footprint

        except Exception as e:
            import traceback
            with open("C:/Log/kicad_plugin_error.txt", "w") as f:
                f.write(traceback.format_exc())
            raise Exception(f"生成SOIC封装错误: {str(e)}")

    def _add_soic_reference(self, footprint, body_length):
        """添加参考标识"""
        # 设置参考文本
        footprint.SetReference("REF**")

        # 设置参考文本属性
        ref = footprint.Reference()
        ref.SetText("REF**")
        ref.SetLayer(pcbnew.F_SilkS)
        ref.SetPosition(pcbnew.VECTOR2I(
            0,
            pcbnew.FromMM(-body_length / 2 - 1.0)  # 在封装下方1mm
        ))
        ref.SetTextSize(pcbnew.VECTOR2I(
            pcbnew.FromMM(1.0),
            pcbnew.FromMM(1.0)
        ))
        ref.SetTextThickness(pcbnew.FromMM(0.15))
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)

    def _add_soic_value(self, footprint, package_name, body_length):
        """添加值标识"""
        # 设置值文本
        footprint.SetValue(package_name)

        # 设置值文本属性
        val = footprint.Value()
        val.SetText(package_name)
        val.SetLayer(pcbnew.F_Fab)
        val.SetPosition(pcbnew.VECTOR2I(
            0,
            pcbnew.FromMM(body_length / 2 + 1.0)  # 在封装上方1mm
        ))
        val.SetTextSize(pcbnew.VECTOR2I(
            pcbnew.FromMM(1.0),
            pcbnew.FromMM(1.0)
        ))
        val.SetTextThickness(pcbnew.FromMM(0.15))
        val.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)

    def _get_soic_pad_width(self, pitch, params):
        """
        获取或计算SOIC焊盘宽度
        焊盘宽度通常为引脚间距的40%-60%
        """
        # 尝试从参数中获取
        pad_width = params.get('Pad Width', params.get('Lead Width', None))
        if pad_width is not None and pad_width != '' and float(pad_width) > 0:
            return float(pad_width)

        # 如果没有提供，根据间距计算默认值
        # 标准SOIC焊盘宽度约为间距的50%
        default_width = pitch * 0.5

        # 限制最小和最大宽度
        min_width = 0.2  # 最小0.2mm
        max_width = 0.8  # 最大0.8mm

        if default_width < min_width:
            default_width = min_width
        elif default_width > max_width:
            default_width = max_width

        print(f"焊盘宽度未指定，使用计算值: {default_width:.2f}mm (基于间距{pitch}mm)")
        return default_width

    def _get_soic_pad_length(self, pitch, params):
        """
        获取或计算SOIC焊盘长度
        焊盘长度通常为引脚间距的60%-80%
        """
        # 尝试从参数中获取
        pad_length = params.get('Pad Length', params.get('Foot Length', None))
        if pad_length is not None and pad_length != '' and float(pad_length) > 0:
            return float(pad_length)

        # 如果没有提供，根据间距计算默认值
        # 标准SOIC焊盘长度约为间距的70%
        default_length = pitch * 0.7

        # 限制最小和最大长度
        min_length = 0.4  # 最小0.4mm
        max_length = 1.2  # 最大1.2mm

        if default_length < min_length:
            default_length = min_length
        elif default_length > max_length:
            default_length = max_length

        print(f"焊盘长度未指定，使用计算值: {default_length:.2f}mm (基于间距{pitch}mm)")
        return default_length

    def _get_soic_overall_width(self, pin_count, pitch, pad_length, params):
        """
        获取或计算SOIC总宽度（包括焊盘）
        """
        overall_width = params.get('Overall Width', params.get('OverallWidth', None))
        if overall_width is not None and overall_width != '' and float(overall_width) > 0:
            return float(overall_width)

        # 如果没有提供，根据引脚数和间距计算
        pins_per_side = pin_count // 2
        default_width = (pins_per_side - 1) * pitch + pad_length * 2

        print(f"总宽度未指定，使用计算值: {default_width:.2f}mm")
        return default_width

    def _add_soic_pads(self, footprint, params):
        """添加焊盘"""
        pin_count = int(params.get('Pin Count'))
        pitch = float(params.get('Pitch'))
        # pad_width = float(params.get('Pad Width', 0))
        # pad_length = float(params.get('Pad Length', 0))
        pad_width = self._get_soic_pad_width(pitch, params)
        pad_length = self._get_soic_pad_length(pitch, params)
        overall_width = float(params.get('Overall Width', 6.0))

        # 计算行间距
        row_spacing = overall_width - pad_length

        # 每边的引脚数
        pins_per_side = pin_count // 2

        for i in range(pins_per_side):
            # 计算Y位置
            y_pos = (i - (pins_per_side - 1) / 2) * pitch

            # 左侧焊盘（引脚1开始）
            pad_num_left = i + 1
            x_pos_left = -row_spacing / 2

            pad_left = pcbnew.PAD(footprint)
            pad_left.SetNumber(str(pad_num_left))
            pad_left.SetShape(pcbnew.PAD_SHAPE_RECT)
            # 或者使用圆角矩形：pcbnew.PAD_SHAPE_ROUNDRECT
            # pad_left.SetRoundRectRadiusRatio(0.25)  # 设置圆角比例

            pad_left.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

            # 设置焊盘尺寸
            pad_left.SetSize(pcbnew.VECTOR2I(
                pcbnew.FromMM(pad_length),
                pcbnew.FromMM(pad_width)
            ))

            # 设置焊盘位置
            pad_left.SetPosition(pcbnew.VECTOR2I(
                pcbnew.FromMM(x_pos_left),
                pcbnew.FromMM(y_pos)
            ))

            # 设置焊盘层
            layerset = pcbnew.LSET()
            layerset.AddLayer(pcbnew.F_Cu)  # 顶层铜
            layerset.AddLayer(pcbnew.F_Paste)  # 顶层焊膏
            layerset.AddLayer(pcbnew.F_Mask)  # 顶层阻焊
            pad_left.SetLayerSet(layerset)

            footprint.Add(pad_left)

            # 右侧焊盘（从最后一个引脚开始）
            pad_num_right = pin_count - i
            x_pos_right = row_spacing / 2

            pad_right = pcbnew.PAD(footprint)
            pad_right.SetNumber(str(pad_num_right))
            pad_right.SetShape(pcbnew.PAD_SHAPE_RECT)
            pad_right.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

            # 设置焊盘尺寸
            pad_right.SetSize(pcbnew.VECTOR2I(
                pcbnew.FromMM(pad_length),
                pcbnew.FromMM(pad_width)
            ))

            # 设置焊盘位置
            pad_right.SetPosition(pcbnew.VECTOR2I(
                pcbnew.FromMM(x_pos_right),
                pcbnew.FromMM(y_pos)
            ))

            # 设置焊盘层
            layerset = pcbnew.LSET()
            layerset.AddLayer(pcbnew.F_Cu)
            layerset.AddLayer(pcbnew.F_Paste)
            layerset.AddLayer(pcbnew.F_Mask)
            pad_right.SetLayerSet(layerset)

            footprint.Add(pad_right)

    def _add_soic_silkscreen(self, footprint, params):
        """添加丝印层"""
        body_width = float(params.get('Package Body Width'))
        body_length = float(params.get('Package Body Length'))
        pin_count = int(params.get('Pin Count'))
        pitch = float(params.get('Pitch'))
        # pad_width = float(params.get('Pad Width', params.get('Lead Width')))
        # pad_length = float(params.get('Pad Length', params.get('Foot Length')))
        pad_width = self._get_soic_pad_width(pitch, params)
        pad_length = self._get_soic_pad_length(pitch, params)

        # 丝印线宽
        line_width = pcbnew.FromMM(0.12)

        # 计算丝印边界
        silk_offset = 0.15  # 距离焊盘的间隙
        x_silk = body_width / 2
        y_silk = body_length / 2

        pins_per_side = pin_count // 2
        y_top_pad = -(pins_per_side - 1) / 2 * pitch - pad_width / 2
        y_bottom_pad = (pins_per_side - 1) / 2 * pitch + pad_width / 2

        # 左侧线（分两段，避开焊盘）
        if y_top_pad - silk_offset > -y_silk:
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_silk),
                pcbnew.FromMM(-y_silk)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_silk),
                pcbnew.FromMM(y_top_pad - silk_offset)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        if y_bottom_pad + silk_offset < y_silk:
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_silk),
                pcbnew.FromMM(y_bottom_pad + silk_offset)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_silk),
                pcbnew.FromMM(y_silk)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # 右侧线（完整）
        line = pcbnew.PCB_SHAPE(footprint)
        line.SetShape(pcbnew.S_SEGMENT)
        line.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_silk),
            pcbnew.FromMM(-y_silk)
        ))
        line.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_silk),
            pcbnew.FromMM(y_silk)
        ))
        line.SetLayer(pcbnew.F_SilkS)
        line.SetWidth(line_width)
        footprint.Add(line)

        # 顶部线
        line = pcbnew.PCB_SHAPE(footprint)
        line.SetShape(pcbnew.S_SEGMENT)
        line.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(-x_silk),
            pcbnew.FromMM(-y_silk)
        ))
        line.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_silk),
            pcbnew.FromMM(-y_silk)
        ))
        line.SetLayer(pcbnew.F_SilkS)
        line.SetWidth(line_width)
        footprint.Add(line)

        # 底部线
        line = pcbnew.PCB_SHAPE(footprint)
        line.SetShape(pcbnew.S_SEGMENT)
        line.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(-x_silk),
            pcbnew.FromMM(y_silk)
        ))
        line.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_silk),
            pcbnew.FromMM(y_silk)
        ))
        line.SetLayer(pcbnew.F_SilkS)
        line.SetWidth(line_width)
        footprint.Add(line)

        # Pin 1标记（圆点）
        marker = pcbnew.PCB_SHAPE(footprint)
        marker.SetShape(pcbnew.S_CIRCLE)
        marker.SetLayer(pcbnew.F_SilkS)
        marker.SetWidth(line_width)

        # 计算标记位置（在封装左上角外部）
        marker_offset = 0.4
        marker_center = pcbnew.VECTOR2I(
            pcbnew.FromMM(-x_silk - marker_offset),
            pcbnew.FromMM(-y_silk - marker_offset)
        )
        marker_radius = pcbnew.FromMM(0.2)

        marker.SetCenter(marker_center)
        marker.SetRadius(marker_radius)
        footprint.Add(marker)

    def _add_soic_courtyard(self, footprint, params):
        """添加禁止布线层（Courtyard）"""
        overall_width = float(params.get('Overall Width'))
        body_length = float(params.get('Package Body Length'))

        courtyard_margin = 0.25  # 外扩间距
        x_court = overall_width / 2 + courtyard_margin
        y_court = body_length / 2 + courtyard_margin

        # 创建矩形
        rect = pcbnew.PCB_SHAPE(footprint)
        rect.SetShape(pcbnew.S_RECT)
        rect.SetLayer(pcbnew.F_CrtYd)
        rect.SetWidth(pcbnew.FromMM(0.05))

        rect.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(-x_court),
            pcbnew.FromMM(-y_court)
        ))
        rect.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_court),
            pcbnew.FromMM(y_court)
        ))

        footprint.Add(rect)

    def _add_soic_fab_layer(self, footprint, params):
        """添加SOIC装配层"""
        body_width = float(params.get('Package Body Width'))
        body_length = float(params.get('Package Body Length'))

        x_fab = body_width / 2
        y_fab = body_length / 2

        line_width = pcbnew.FromMM(0.1)

        # 主体轮廓矩形
        rect = pcbnew.PCB_SHAPE(footprint)
        rect.SetShape(pcbnew.S_RECT)
        rect.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(-x_fab),
            pcbnew.FromMM(-y_fab)
        ))
        rect.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_fab),
            pcbnew.FromMM(y_fab)
        ))
        rect.SetLayer(pcbnew.F_Fab)
        rect.SetWidth(line_width)
        footprint.Add(rect)

        # Pin 1标记（斜角）
        chamfer = 0.5  # 斜角长度
        if body_width >= chamfer and body_length >= chamfer:
            line1 = pcbnew.PCB_SHAPE(footprint)
            line1.SetShape(pcbnew.S_SEGMENT)
            line1.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_fab),
                pcbnew.FromMM(-y_fab + chamfer)
            ))
            line1.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_fab + chamfer),
                pcbnew.FromMM(-y_fab)
            ))
            line1.SetLayer(pcbnew.F_Fab)
            line1.SetWidth(line_width)
            footprint.Add(line1)

    def _generate_qfn_footprint(self, package_name, params):
        """
        生成QFN封装（完整版本）
        """
        try:
            ep_size_x = float(params.get('Exposed Pad Size X', 0))
            ep_size_y = float(params.get('Exposed Pad Size Y', 0))
            ep_land_x = float(params.get('Exposed Pad Land Size X', 0))
            ep_land_y = float(params.get('Exposed Pad Land Size Y', 0))

            # 提取QFN参数，同时检查是否为有效数值
            try:
                pin_count_x = int(params.get('Pin Count X', params.get('PinCountX', 0)))
                if pin_count_x <= 0:
                    raise ValueError("X方向引脚数必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的X方向引脚数参数")

            try:
                pin_count_y = int(params.get('Pin Count Y', params.get('PinCountY', 0)))
                if pin_count_y <= 0:
                    raise ValueError("Y方向引脚数必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的Y方向引脚数参数")

            try:
                pad_width = float(params.get('Pad Width', 0))
                if pad_width <= 0:
                    raise ValueError("焊盘宽度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的焊盘宽度参数")

            try:
                pad_length = float(params.get('Pad Length', 0))
                if pad_length <= 0:
                    raise ValueError("焊盘长度必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的焊盘长度参数")

            try:
                pitch_x = float(params.get('Lead Pitch X', params.get('LeadPitchX', 0)))
                if pitch_x <= 0:
                    raise ValueError("X方向间距必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的X方向间距参数")

            try:
                pitch_y = float(params.get('Lead Pitch Y', params.get('LeadPitchY', 0)))
                if pitch_y <= 0:
                    raise ValueError("Y方向间距必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的Y方向间距参数")

            try:
                body_x = float(params.get('Package Body Size X', params.get('PackageBodySizeX', 0)))
                if body_x <= 0:
                    raise ValueError("封装体X尺寸必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的封装体X尺寸参数")

            try:
                body_y = float(params.get('Package Body Size Y', params.get('PackageBodySizeY', 0)))
                if body_y <= 0:
                    raise ValueError("封装体Y尺寸必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的封装体Y尺寸参数")

            # 计算总引脚数
            total_pins = (pin_count_x + pin_count_y) * 2

            # 验证焊盘长度
            if pad_length <= 0 or pad_width <= 0:
                raise ValueError("焊盘尺寸必须大于0")

            # 创建封装对象
            board = pcbnew.GetBoard()
            footprint = pcbnew.FOOTPRINT(board)

            # 设置封装ID
            footprint.SetFPID(pcbnew.LIB_ID("", package_name))

            # 设置描述和关键字
            footprint.SetLibDescription(
                f"QFN, {total_pins} Pin ({pin_count_x}x{pin_count_y}), "
                f"pitch {pitch_x}mm x {pitch_y}mm, "
                f"body size {body_x}x{body_y}mm"
            )
            footprint.SetKeywords("QFN DFN")

            # 添加参考标识
            self._add_qfn_reference(footprint, body_y)

            # 添加值标识
            footprint.SetValue(package_name)
            self._add_qfn_value(footprint, package_name, body_y)

            # 添加周边焊盘
            self._add_qfn_perimeter_pads(footprint, params)

            # 添加中心散热焊盘（如果有）
            if ep_size_x > 0 and ep_size_y > 0:
                self._add_qfn_thermal_pad(footprint, params)

            # 添加丝印层
            self._add_qfn_silkscreen(footprint, params)

            # 添加禁止布线层
            self._add_qfn_courtyard(footprint, params)

            # 添加装配文档层
            self._add_qfn_fab_layer(footprint, params)

            return footprint

        except Exception as e:
            raise Exception(f"生成QFN封装错误: {str(e)}")

    def _add_qfn_reference(self, footprint, body_y):
        """添加QFN参考标识"""
        # 设置参考文本
        footprint.SetReference("REF**")

        # 设置参考文本属性
        ref = footprint.Reference()
        ref.SetText("REF**")
        ref.SetLayer(pcbnew.F_SilkS)
        ref.SetPosition(pcbnew.VECTOR2I(
            0,
            pcbnew.FromMM(-body_y / 2 - 1.0)  # 在封装下方1mm
        ))
        ref.SetTextSize(pcbnew.VECTOR2I(
            pcbnew.FromMM(1.0),
            pcbnew.FromMM(1.0)
        ))
        ref.SetTextThickness(pcbnew.FromMM(0.15))
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)

    def _add_qfn_value(self, footprint, package_name, body_y):
        """添加QFN值标识"""
        # 设置值文本属性
        val = footprint.Value()
        val.SetText(package_name)
        val.SetLayer(pcbnew.F_Fab)
        val.SetPosition(pcbnew.VECTOR2I(
            0,
            pcbnew.FromMM(body_y / 2 + 1.0)  # 在封装上方1mm
        ))
        val.SetTextSize(pcbnew.VECTOR2I(
            pcbnew.FromMM(1.0),
            pcbnew.FromMM(1.0)
        ))
        val.SetTextThickness(pcbnew.FromMM(0.15))
        val.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)

    def _add_qfn_perimeter_pads(self, footprint, params):
        """添加QFN周边焊盘 - 修正引脚顺序：左侧从上到下为1,2,3..."""
        pin_count_x = int(params.get('Pin Count X'))
        pin_count_y = int(params.get('Pin Count Y'))
        pitch_x = float(params.get('Lead Pitch X'))
        pitch_y = float(params.get('Lead Pitch Y'))
        pad_width = float(params.get('Pad Width'))
        pad_length = float(params.get('Pad Length'))
        body_x = float(params.get('Package Body Size X'))
        body_y = float(params.get('Package Body Size Y'))

        # 获取Pin 1位置信息
        pin1_location = params.get('Pin 1 Visual Location', 'UPPER LEFT').upper()

        # 计算焊盘位置（从封装本体边缘算起）
        pad_offset_x = body_x / 2 + pad_length / 2
        pad_offset_y = body_y / 2 + pad_length / 2

        pin_number = 1

        # 根据Pin 1位置决定起始方向
        if pin1_location == 'UPPER LEFT' or pin1_location == '':
            # **标准QFN：左上角开始，逆时针方向**
            # 左侧焊盘从上到下：1, 2, 3, ...

            # 1. 左侧焊盘（从上到下）- Pin 1在左上角
            for i in range(pin_count_y):
                x_pos = -pad_offset_x  # 左侧
                # 修正：从上到下，所以应该是 -y 方向
                # i=0时在最上方，i增大时向下移动
                y_pos = -pad_offset_y + (i * pitch_y) + pitch_y / 2  # 从上到下计算

                # 或者使用更清晰的计算方式：
                # 总高度 = (pin_count_y - 1) * pitch_y
                # 最上方位置 = -总高度/2
                # 每个焊盘位置 = 最上方位置 + i * pitch_y

                total_height = (pin_count_y - 1) * pitch_y
                top_position = -total_height / 2
                y_pos = top_position + (i * pitch_y)

                pad = pcbnew.PAD(footprint)
                pad.SetNumber(str(pin_number))
                pad.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

                # 设置焊盘尺寸（垂直方向）
                pad.SetSize(pcbnew.VECTOR2I(
                    pcbnew.FromMM(pad_length),
                    pcbnew.FromMM(pad_width)
                ))

                # 设置焊盘位置
                pad.SetPosition(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_pos),
                    pcbnew.FromMM(y_pos)
                ))

                # 设置方向（垂直）
                pad.SetOrientation(pcbnew.EDA_ANGLE(0.0, pcbnew.DEGREES_T))

                # 设置焊盘层
                layerset = pcbnew.LSET()
                layerset.AddLayer(pcbnew.F_Cu)
                layerset.AddLayer(pcbnew.F_Paste)
                layerset.AddLayer(pcbnew.F_Mask)
                pad.SetLayerSet(layerset)

                footprint.Add(pad)
                pin_number += 1

            # 2. 底部焊盘（从左到右）- 继续逆时针
            for i in range(pin_count_x):
                # 从左到右
                total_width = (pin_count_x - 1) * pitch_x
                left_position = -total_width / 2
                x_pos = left_position + (i * pitch_x)
                y_pos = pad_offset_y  # 底部

                pad = pcbnew.PAD(footprint)
                pad.SetNumber(str(pin_number))
                pad.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

                # 设置焊盘尺寸
                pad.SetSize(pcbnew.VECTOR2I(
                    pcbnew.FromMM(pad_width),
                    pcbnew.FromMM(pad_length)
                ))

                # 设置焊盘位置
                pad.SetPosition(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_pos),
                    pcbnew.FromMM(y_pos)
                ))

                # 设置焊盘层
                layerset = pcbnew.LSET()
                layerset.AddLayer(pcbnew.F_Cu)
                layerset.AddLayer(pcbnew.F_Paste)
                layerset.AddLayer(pcbnew.F_Mask)
                pad.SetLayerSet(layerset)

                footprint.Add(pad)
                pin_number += 1

            # 3. 右侧焊盘（从下到上）- 继续逆时针
            for i in range(pin_count_y):
                x_pos = pad_offset_x  # 右侧
                # 从下到上，所以i=0时在最下方
                total_height = (pin_count_y - 1) * pitch_y
                bottom_position = total_height / 2  # 最下方是正数
                y_pos = bottom_position - (i * pitch_y)  # 从下向上

                pad = pcbnew.PAD(footprint)
                pad.SetNumber(str(pin_number))
                pad.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

                # 设置焊盘尺寸（垂直方向）
                pad.SetSize(pcbnew.VECTOR2I(
                    pcbnew.FromMM(pad_length),
                    pcbnew.FromMM(pad_width)
                ))

                # 设置焊盘位置
                pad.SetPosition(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_pos),
                    pcbnew.FromMM(y_pos)
                ))

                # 设置方向（垂直）
                pad.SetOrientation(pcbnew.EDA_ANGLE(0.0, pcbnew.DEGREES_T))

                # 设置焊盘层
                layerset = pcbnew.LSET()
                layerset.AddLayer(pcbnew.F_Cu)
                layerset.AddLayer(pcbnew.F_Paste)
                layerset.AddLayer(pcbnew.F_Mask)
                pad.SetLayerSet(layerset)

                footprint.Add(pad)
                pin_number += 1

            # 4. 顶部焊盘（从右到左）- 完成逆时针一圈
            for i in range(pin_count_x):
                # 从右到左
                total_width = (pin_count_x - 1) * pitch_x
                right_position = total_width / 2  # 最右侧是正数
                x_pos = right_position - (i * pitch_x)  # 从右向左
                y_pos = -pad_offset_y  # 顶部

                pad = pcbnew.PAD(footprint)
                pad.SetNumber(str(pin_number))
                pad.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

                # 设置焊盘尺寸
                pad.SetSize(pcbnew.VECTOR2I(
                    pcbnew.FromMM(pad_width),
                    pcbnew.FromMM(pad_length)
                ))

                # 设置焊盘位置
                pad.SetPosition(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_pos),
                    pcbnew.FromMM(y_pos)
                ))

                # 设置焊盘层
                layerset = pcbnew.LSET()
                layerset.AddLayer(pcbnew.F_Cu)
                layerset.AddLayer(pcbnew.F_Paste)
                layerset.AddLayer(pcbnew.F_Mask)
                pad.SetLayerSet(layerset)

                footprint.Add(pad)
                pin_number += 1

        elif pin1_location == 'LOWER LEFT':
            # 如果Pin 1在左下角（类似SOIC），则顺时针方向
            # ...（原有代码）
            pass
        else:
            # 默认使用标准QFN顺序（左上角，逆时针）
            pass

    def _add_qfn_thermal_pad(self, footprint, params):
        """添加QFN中心散热焊盘"""
        ep_size_x = float(params.get('Exposed Pad Size X', 0))
        ep_size_y = float(params.get('Exposed Pad Size Y', 0))
        ep_land_x = float(params.get('Exposed Pad Land Size X', 0))
        ep_land_y = float(params.get('Exposed Pad Land Size Y', 0))
        pin_count_x = int(params.get('Pin Count X', 0))
        pin_count_y = int(params.get('Pin Count Y', 0))

        if ep_land_x <= 0 or ep_land_y <= 0:
            return

        # 计算总引脚数作为散热焊盘编号
        total_pins = (pin_count_x + pin_count_y) * 2
        thermal_pad_number = total_pins + 1

        # 创建散热焊盘
        pad = pcbnew.PAD(footprint)
        pad.SetNumber(str(thermal_pad_number))
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)  # 或使用 PAD_SHAPE_ROUNDRECT
        # pad.SetRoundRectRadiusRatio(0.1)

        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

        # 设置焊盘尺寸
        pad.SetSize(pcbnew.VECTOR2I(
            pcbnew.FromMM(ep_land_x),
            pcbnew.FromMM(ep_land_y)
        ))

        # 设置焊盘位置
        pad.SetPosition(pcbnew.VECTOR2I(0, 0))

        # 设置焊盘层
        layerset = pcbnew.LSET()
        layerset.AddLayer(pcbnew.F_Cu)
        layerset.AddLayer(pcbnew.F_Paste)
        layerset.AddLayer(pcbnew.F_Mask)
        pad.SetLayerSet(layerset)

        footprint.Add(pad)

    def _add_qfn_silkscreen(self, footprint, params):
        """添加QFN丝印层"""
        body_x = float(params.get('Package Body Size X'))
        body_y = float(params.get('Package Body Size Y'))
        pad_width = float(params.get('Pad Width'))
        pad_length = float(params.get('Pad Length'))
        pin_count_x = int(params.get('Pin Count X'))
        pin_count_y = int(params.get('Pin Count Y'))
        pitch_x = float(params.get('Lead Pitch X'))
        pitch_y = float(params.get('Lead Pitch Y'))

        # 丝印线宽
        line_width = pcbnew.FromMM(0.12)

        # 丝印边界
        silk_x = body_x / 2
        silk_y = body_y / 2
        silk_offset = 0.15  # 距离焊盘的间隙

        # 计算焊盘边缘
        bottom_pad_edge = body_y / 2 + pad_length

        # 左侧焊盘占据的Y范围
        left_pad_y_start = -(pin_count_y - 1) / 2 * pitch_y - pad_width / 2 - silk_offset
        left_pad_y_end = (pin_count_y - 1) / 2 * pitch_y + pad_width / 2 + silk_offset

        # 左下角竖线
        if left_pad_y_end < silk_y:
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(left_pad_y_end)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # 左上角竖线
        if left_pad_y_start > -silk_y + 0.5:  # 为Pin1标记留出空间
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(-silk_y)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(left_pad_y_start - 0.5)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # 右侧线
        line = pcbnew.PCB_SHAPE(footprint)
        line.SetShape(pcbnew.S_SEGMENT)
        line.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(silk_x),
            pcbnew.FromMM(-silk_y)
        ))
        line.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(silk_x),
            pcbnew.FromMM(silk_y)
        ))
        line.SetLayer(pcbnew.F_SilkS)
        line.SetWidth(line_width)
        footprint.Add(line)

        # 计算顶部和底部焊盘占据的X范围
        top_pad_x_start = -(pin_count_x - 1) / 2 * pitch_x - pad_width / 2 - silk_offset
        top_pad_x_end = (pin_count_x - 1) / 2 * pitch_x + pad_width / 2 + silk_offset

        # 顶部线 - 左段
        if top_pad_x_start > -silk_x + 0.5:  # 为Pin1标记留出空间
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x + 0.5),
                pcbnew.FromMM(-silk_y)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(top_pad_x_start),
                pcbnew.FromMM(-silk_y)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # 顶部线 - 右段
        if top_pad_x_end < silk_x:
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(top_pad_x_end),
                pcbnew.FromMM(-silk_y)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(silk_x),
                pcbnew.FromMM(-silk_y)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # 底部线 - 左段
        if top_pad_x_start > -silk_x:
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(top_pad_x_start),
                pcbnew.FromMM(silk_y)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # 底部线 - 右段
        if top_pad_x_end < silk_x:
            line = pcbnew.PCB_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(top_pad_x_end),
                pcbnew.FromMM(silk_y)
            ))
            line.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line.SetLayer(pcbnew.F_SilkS)
            line.SetWidth(line_width)
            footprint.Add(line)

        # Pin 1标记（左上角圆点）
        marker = pcbnew.PCB_SHAPE(footprint)
        marker.SetShape(pcbnew.S_CIRCLE)
        marker.SetLayer(pcbnew.F_SilkS)
        marker.SetWidth(line_width)

        marker_offset = 0.4
        marker_center = pcbnew.VECTOR2I(
            pcbnew.FromMM(-silk_x - marker_offset),
            pcbnew.FromMM(-silk_y - marker_offset)
        )
        marker_radius = pcbnew.FromMM(0.2)

        marker.SetCenter(marker_center)
        marker.SetRadius(marker_radius)
        footprint.Add(marker)

    def _add_qfn_courtyard(self, footprint, params):
        """添加QFN禁止布线层（Courtyard）"""
        body_x = float(params.get('Package Body Size X'))
        body_y = float(params.get('Package Body Size Y'))
        pad_length = float(params.get('Pad Length'))

        # Courtyard外扩
        courtyard_margin = 0.25
        x_court = body_x / 2 + pad_length + courtyard_margin
        y_court = body_y / 2 + pad_length + courtyard_margin

        # 创建矩形
        rect = pcbnew.PCB_SHAPE(footprint)
        rect.SetShape(pcbnew.S_RECT)
        rect.SetLayer(pcbnew.F_CrtYd)
        rect.SetWidth(pcbnew.FromMM(0.05))

        rect.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(-x_court),
            pcbnew.FromMM(-y_court)
        ))
        rect.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(x_court),
            pcbnew.FromMM(y_court)
        ))

        footprint.Add(rect)

    def _add_qfn_fab_layer(self, footprint, params):
        """添加QFN装配文档层"""
        body_x = float(params.get('Package Body Size X'))
        body_y = float(params.get('Package Body Size Y'))
        ep_size_x = float(params.get('Exposed Pad Size X'))
        ep_size_y = float(params.get('Exposed Pad Size Y'))

        line_width = pcbnew.FromMM(0.1)

        # 主体矩形
        rect = pcbnew.PCB_SHAPE(footprint)
        rect.SetShape(pcbnew.S_RECT)
        rect.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(-body_x / 2),
            pcbnew.FromMM(-body_y / 2)
        ))
        rect.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(body_x / 2),
            pcbnew.FromMM(body_y / 2)
        ))
        rect.SetLayer(pcbnew.F_Fab)
        rect.SetWidth(line_width)
        footprint.Add(rect)

        # Pin 1标记（左上角斜角）
        chamfer = 0.5
        if body_x >= chamfer * 2 and body_y >= chamfer * 2:
            line1 = pcbnew.PCB_SHAPE(footprint)
            line1.SetShape(pcbnew.S_SEGMENT)
            line1.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-body_x / 2),
                pcbnew.FromMM(-body_y / 2 + chamfer)
            ))
            line1.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-body_x / 2 + chamfer),
                pcbnew.FromMM(-body_y / 2)
            ))
            line1.SetLayer(pcbnew.F_Fab)
            line1.SetWidth(line_width)
            footprint.Add(line1)

        # 散热焊盘轮廓（如果存在）
        if ep_size_x > 0 and ep_size_y > 0:
            ep_rect = pcbnew.PCB_SHAPE(footprint)
            ep_rect.SetShape(pcbnew.S_RECT)
            ep_rect.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-ep_size_x / 2),
                pcbnew.FromMM(-ep_size_y / 2)
            ))
            ep_rect.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(ep_size_x / 2),
                pcbnew.FromMM(ep_size_y / 2)
            ))
            ep_rect.SetLayer(pcbnew.F_Fab)
            ep_rect.SetWidth(line_width)
            footprint.Add(ep_rect)

    def _generate_bga_footprint(self, package_name, params):
        """
        生成BGA封装（完整版本）
        """
        try:
            ball_diameter = float(params.get('Ball Diameter', 1.2))
            a1_location = params.get('A1 Ball Visual Location', 'lower left').lower()

            # 提取BGA参数，同时检查是否为有效数值
            try:
                ball_pitch_x = float(params.get('Ball Pitch X', params.get('BallPitchX', 0)))
                if ball_pitch_x <= 0:
                    raise ValueError("X方向球间距必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的X方向球间距参数")

            try:
                ball_pitch_y = float(params.get('Ball Pitch Y', params.get('BallPitchY', 0)))
                if ball_pitch_y <= 0:
                    raise ValueError("Y方向球间距必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的Y方向球间距参数")

            try:
                ball_count_x = int(params.get('Ball Count X', 0))
                if ball_count_x <= 0:
                    raise ValueError("X方向球个数必须大于0")
            except (ValueError, TypeError):
                raise ValueError("X方向球个数无效")

            try:
                ball_count_y = int(params.get('Ball Count Y', 0))
                if ball_count_y <= 0:
                    raise ValueError("Y方向球个数必须大于0")
            except (ValueError, TypeError):
                raise ValueError("Y方向球个数无效")

            try:
                ball_diameter = float(params.get('Ball Diameter', params.get('BallDiameter', 0)))
                if ball_diameter <= 0:
                    raise ValueError("球直径必须大于0")
            except (ValueError, TypeError):
                raise ValueError("无效的球直径参数")

            try:
                package_body_x = float(params.get('Package Body Size X',0))
                if package_body_x <= 0:
                    raise ValueError("X方向本体尺寸必须大于0")
            except (ValueError, TypeError):
                raise ValueError("X方向本体尺寸参数无效")

            try:
                package_body_y = float(params.get('Package Body Size Y',0))
                if package_body_y <= 0:
                    raise ValueError("Y方向本体尺寸必须大于0")
            except (ValueError, TypeError):
                raise ValueError("Y方向本体尺寸参数无效")

            a1_location = params.get('A1 Ball Visual Location', 'lower left').lower()

            board = pcbnew.GetBoard()
            if not board:
                raise Exception("无法获取当前板子")

            footprint = pcbnew.FOOTPRINT(board)

            # 设置封装ID
            footprint.SetFPID(pcbnew.LIB_ID("", package_name))

            # 设置描述和关键字
            total_balls = ball_count_x * ball_count_y
            footprint.SetLibDescription(
                f"BGA, {total_balls} Ball ({ball_count_x}x{ball_count_y}), "
                f"pitch {ball_pitch_x}mm x {ball_pitch_y}mm, "
                f"ball dia {ball_diameter}mm, body size {package_body_x}x{package_body_y}mm"
            )
            footprint.SetKeywords("BGA")

            # 设置参考和值
            footprint.SetReference("U**")
            footprint.SetValue(package_name)

            # 添加参考标识
            ref = footprint.Reference()
            ref.SetText("REF**")
            ref.SetLayer(pcbnew.F_SilkS)
            ref.SetPosition(pcbnew.VECTOR2I(
                0,
                pcbnew.FromMM(-package_body_y / 2 - 1.5)
            ))
            ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.0), pcbnew.FromMM(1.0)))
            ref.SetTextThickness(pcbnew.FromMM(0.15))
            ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)

            # 添加值标识
            val = footprint.Value()
            val.SetText(package_name)
            val.SetLayer(pcbnew.F_Fab)
            val.SetPosition(pcbnew.VECTOR2I(
                0,
                pcbnew.FromMM(package_body_y / 2 + 1.5)
            ))
            val.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.0), pcbnew.FromMM(1.0)))
            val.SetTextThickness(pcbnew.FromMM(0.15))
            val.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)

            # 添加BGA焊盘（球）
            self._add_bga_pads(footprint, params)

            # 添加丝印层
            self._add_bga_silkscreen(footprint, params)

            # 添加禁止布线层
            self._add_bga_courtyard(footprint, params)

            # 添加装配文档层
            self._add_bga_fab_layer(footprint, params)

            return footprint

        except Exception as e:
            raise Exception(f"生成BGA封装错误: {str(e)}")

    def _add_bga_pads(self, footprint, params):
        """添加BGA焊盘（球）- 使用A1, A2, B1, B2格式编号"""
        try:
            ball_pitch_x = float(params.get('Ball Pitch X', 2.42))
            ball_pitch_y = float(params.get('Ball Pitch Y', 2.42))
            ball_count_x = int(params.get('Ball Count X', 5))
            ball_count_y = int(params.get('Ball Count Y', 5))
            ball_diameter = float(params.get('Ball Diameter', 1.2))
            a1_location = params.get('A1 Ball Visual Location', 'lower left').lower()
            ball_shape = params.get('Ball Visual Shape', 'solid circle')
            # 计算BGA阵列的总尺寸
            total_width_x = (ball_count_x - 1) * ball_pitch_x
            total_width_y = (ball_count_y - 1) * ball_pitch_y

            # 字母行编号（A, B, C, D, ...）
            row_letters = []
            for i in range(ball_count_y):
                row_letters.append(chr(ord('A') + i))

            # 确定A1球的位置并设置焊盘编号顺序
            ball_number = 1

            # 获取球形状
            if ball_shape is None or ball_shape == '':
                ball_shape = 'solid circle'
            ball_shape = ball_shape.lower()

            # BGA焊盘通常使用圆形
            for row in range(ball_count_y):
                for col in range(ball_count_x):
                    # 根据A1位置确定行列顺序
                    if a1_location == 'lower left':
                        # A1在左下角：行从下到上，列从左到右
                        actual_row = ball_count_y - 1 - row  # 从下到上
                        actual_col = col  # 从左到右
                        y_pos = -total_width_y / 2 + actual_row * ball_pitch_y
                        x_pos = -total_width_x / 2 + actual_col * ball_pitch_x

                        # 行字母：从下到上，所以最下面是A
                        row_letter = row_letters[ball_count_y - 1 - row]
                        col_number = actual_col + 1

                    elif a1_location == 'upper left':
                        # A1在左上角：行从上到下，列从左到右
                        actual_row = row
                        actual_col = col
                        y_pos = -total_width_y / 2 + actual_row * ball_pitch_y
                        x_pos = -total_width_x / 2 + actual_col * ball_pitch_x

                        # 行字母：从上到下，所以最上面是A
                        row_letter = row_letters[row]
                        col_number = actual_col + 1

                    elif a1_location == 'lower right':
                        # A1在右下角：行从下到上，列从右到左
                        actual_row = ball_count_y - 1 - row
                        actual_col = ball_count_x - 1 - col
                        y_pos = -total_width_y / 2 + actual_row * ball_pitch_y
                        x_pos = total_width_x / 2 - actual_col * ball_pitch_x

                        # 行字母：从下到上
                        row_letter = row_letters[ball_count_y - 1 - row]
                        col_number = ball_count_x - actual_col

                    elif a1_location == 'upper right':
                        # A1在右上角：行从上到下，列从右到左
                        actual_row = row
                        actual_col = ball_count_x - 1 - col
                        y_pos = -total_width_y / 2 + actual_row * ball_pitch_y
                        x_pos = total_width_x / 2 - actual_col * ball_pitch_x

                        # 行字母：从上到下
                        row_letter = row_letters[row]
                        col_number = ball_count_x - actual_col

                    else:
                        # 默认使用lower left
                        actual_row = ball_count_y - 1 - row
                        actual_col = col
                        y_pos = -total_width_y / 2 + actual_row * ball_pitch_y
                        x_pos = -total_width_x / 2 + actual_col * ball_pitch_x

                        row_letter = row_letters[ball_count_y - 1 - row]
                        col_number = actual_col + 1

                    # 生成球编号（例如：A1, A2, B1, B2）
                    ball_number_str = f"{row_letter}{col_number}"

                    # 创建焊盘
                    pad = pcbnew.PAD(footprint)
                    pad.SetNumber(ball_number_str)

                    # BGA焊盘通常是圆形
                    if 'circle' in ball_shape:
                        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
                    else:
                        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)  # 默认圆形

                    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

                    # 设置焊盘尺寸（直径）
                    pad.SetSize(pcbnew.VECTOR2I(
                        pcbnew.FromMM(ball_diameter),
                        pcbnew.FromMM(ball_diameter)
                    ))

                    # 设置焊盘位置
                    pad.SetPosition(pcbnew.VECTOR2I(
                        pcbnew.FromMM(x_pos),
                        pcbnew.FromMM(y_pos)
                    ))

                    # 设置焊盘层 - BGA焊盘通常只需要铜层和阻焊层
                    # 使用标准的SMD焊盘层设置
                    pad.SetLayerSet(pad.SMDMask())

                    footprint.Add(pad)
                    ball_number += 1

            print(f"已添加 {ball_number - 1} 个BGA焊盘")

        except Exception as e:
            print(f"添加BGA焊盘错误: {str(e)}")
            raise

    def _add_bga_fab_layer(self, footprint, params):
        """添加BGA装配文档层（最内层）"""
        try:
            package_body_x = float(params.get('Package Body Size X', 6.25))
            package_body_y = float(params.get('Package Body Size Y', 6.25))
            a1_location = params.get('A1 Ball Visual Location', 'lower left').lower()
            line_width = pcbnew.FromMM(0.1)

            # 装配层就是本体尺寸（最内层）
            x_fab = package_body_x / 2
            y_fab = package_body_y / 2

            rect = pcbnew.PCB_SHAPE(footprint)
            rect.SetShape(pcbnew.S_RECT)
            rect.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_fab),
                pcbnew.FromMM(-y_fab)
            ))
            rect.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(x_fab),
                pcbnew.FromMM(y_fab)
            ))
            rect.SetLayer(pcbnew.F_Fab)
            rect.SetWidth(line_width)
            footprint.Add(rect)

            # A1标记 - 在装配层绘制斜角
            chamfer_size = 0.5

            # 根据A1位置确定标记位置
            if a1_location == 'upper left':
                # 左上角斜角 - 切掉左上角
                chamfer_line = pcbnew.PCB_SHAPE(footprint)
                chamfer_line.SetShape(pcbnew.S_SEGMENT)
                chamfer_line.SetStart(pcbnew.VECTOR2I(
                    pcbnew.FromMM(-x_fab),
                    pcbnew.FromMM(-y_fab + chamfer_size)  # 从顶部向下一点
                ))
                chamfer_line.SetEnd(pcbnew.VECTOR2I(
                    pcbnew.FromMM(-x_fab + chamfer_size),
                    pcbnew.FromMM(-y_fab)  # 到顶部
                ))
                chamfer_line.SetLayer(pcbnew.F_Fab)
                chamfer_line.SetWidth(line_width)
                footprint.Add(chamfer_line)

            elif a1_location == 'upper right':
                # 右上角斜角 - 切掉右上角
                chamfer_line = pcbnew.PCB_SHAPE(footprint)
                chamfer_line.SetShape(pcbnew.S_SEGMENT)
                chamfer_line.SetStart(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_fab - chamfer_size),
                    pcbnew.FromMM(-y_fab)  # 从顶部
                ))
                chamfer_line.SetEnd(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_fab),
                    pcbnew.FromMM(-y_fab + chamfer_size)  # 到顶部向下一点
                ))
                chamfer_line.SetLayer(pcbnew.F_Fab)
                chamfer_line.SetWidth(line_width)
                footprint.Add(chamfer_line)

            elif a1_location == 'lower left':
                # 左下角斜角 - 切掉左下角
                chamfer_line = pcbnew.PCB_SHAPE(footprint)
                chamfer_line.SetShape(pcbnew.S_SEGMENT)
                chamfer_line.SetStart(pcbnew.VECTOR2I(
                    pcbnew.FromMM(-x_fab),
                    pcbnew.FromMM(y_fab - chamfer_size)  # 从底部向上一点
                ))
                chamfer_line.SetEnd(pcbnew.VECTOR2I(
                    pcbnew.FromMM(-x_fab + chamfer_size),
                    pcbnew.FromMM(y_fab)  # 到底部
                ))
                chamfer_line.SetLayer(pcbnew.F_Fab)
                chamfer_line.SetWidth(line_width)
                footprint.Add(chamfer_line)

            elif a1_location == 'lower right':
                # 右下角斜角 - 切掉右下角
                chamfer_line = pcbnew.PCB_SHAPE(footprint)
                chamfer_line.SetShape(pcbnew.S_SEGMENT)
                chamfer_line.SetStart(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_fab - chamfer_size),
                    pcbnew.FromMM(y_fab)  # 从底部
                ))
                chamfer_line.SetEnd(pcbnew.VECTOR2I(
                    pcbnew.FromMM(x_fab),
                    pcbnew.FromMM(y_fab - chamfer_size)  # 到底部向上一点
                ))
                chamfer_line.SetLayer(pcbnew.F_Fab)
                chamfer_line.SetWidth(line_width)
                footprint.Add(chamfer_line)

            print("已添加BGA Fab层")

        except Exception as e:
            print(f"添加BGA装配层错误: {str(e)}")

    def _add_bga_silkscreen(self, footprint, params):
        """添加BGA丝印层（中间层）"""
        try:
            package_body_x = float(params.get('Package Body Size X', 6.25))
            package_body_y = float(params.get('Package Body Size Y', 6.25))
            a1_location = params.get('A1 Ball Visual Location', 'lower left').lower()
            # 丝印线宽
            line_width = pcbnew.FromMM(0.12)

            # 丝印边界（比Fab层稍大）
            silk_margin = 0.2
            silk_x = package_body_x / 2 + silk_margin
            silk_y = package_body_y / 2 + silk_margin

            # 创建完整的丝印矩形框
            # 左侧线
            line_left = pcbnew.PCB_SHAPE(footprint)
            line_left.SetShape(pcbnew.S_SEGMENT)
            line_left.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(-silk_y)
            ))
            line_left.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line_left.SetLayer(pcbnew.F_SilkS)
            line_left.SetWidth(line_width)
            footprint.Add(line_left)

            # 右侧线
            line_right = pcbnew.PCB_SHAPE(footprint)
            line_right.SetShape(pcbnew.S_SEGMENT)
            line_right.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(silk_x),
                pcbnew.FromMM(-silk_y)
            ))
            line_right.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line_right.SetLayer(pcbnew.F_SilkS)
            line_right.SetWidth(line_width)
            footprint.Add(line_right)

            # 顶部线
            line_top = pcbnew.PCB_SHAPE(footprint)
            line_top.SetShape(pcbnew.S_SEGMENT)
            line_top.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(-silk_y)
            ))
            line_top.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(silk_x),
                pcbnew.FromMM(-silk_y)
            ))
            line_top.SetLayer(pcbnew.F_SilkS)
            line_top.SetWidth(line_width)
            footprint.Add(line_top)

            # 底部线
            line_bottom = pcbnew.PCB_SHAPE(footprint)
            line_bottom.SetShape(pcbnew.S_SEGMENT)
            line_bottom.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line_bottom.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(silk_x),
                pcbnew.FromMM(silk_y)
            ))
            line_bottom.SetLayer(pcbnew.F_SilkS)
            line_bottom.SetWidth(line_width)
            footprint.Add(line_bottom)

            # A1球标记 - 在丝印上标记A1位置
            marker_offset_x = 0.3
            marker_offset_y = 0.3
            marker_radius = pcbnew.FromMM(0.2)

            if 'lower' in a1_location:
                y_offset = silk_y - marker_offset_y
            else:
                y_offset = -silk_y + marker_offset_y

            if 'left' in a1_location:
                x_offset = -silk_x + marker_offset_x
            else:
                x_offset = silk_x - marker_offset_x

            # A1标记圆点
            a1_marker = pcbnew.PCB_SHAPE(footprint)
            a1_marker.SetShape(pcbnew.S_CIRCLE)
            a1_marker.SetLayer(pcbnew.F_SilkS)
            a1_marker.SetWidth(line_width)
            a1_marker.SetCenter(pcbnew.VECTOR2I(
                pcbnew.FromMM(x_offset),
                pcbnew.FromMM(y_offset)
            ))
            a1_marker.SetRadius(marker_radius)
            footprint.Add(a1_marker)

            print("已添加BGA丝印层")

        except Exception as e:
            print(f"添加BGA丝印层错误: {str(e)}")

    def _add_bga_courtyard(self, footprint, params):
        """添加BGA禁止布线层（最外层）"""
        try:
            ball_pitch_x = float(params.get('Ball Pitch X', 2.42))
            ball_pitch_y = float(params.get('Ball Pitch Y', 2.42))
            ball_count_x = int(params.get('Ball Count X', 5))
            ball_count_y = int(params.get('Ball Count Y', 5))
            ball_diameter = float(params.get('Ball Diameter', 1.2))
            # 计算最边缘焊盘的位置
            total_width_x = (ball_count_x - 1) * ball_pitch_x
            total_width_y = (ball_count_y - 1) * ball_pitch_y

            # 最边缘焊盘中心位置
            max_x = total_width_x / 2
            max_y = total_width_y / 2

            # 焊盘边缘位置（考虑焊盘半径）
            pad_radius = ball_diameter / 2
            courtyard_margin = 0.25  # 外扩间距

            # Courtyard是最外层，要包含所有焊盘并外扩
            x_court = max_x + pad_radius + courtyard_margin
            y_court = max_y + pad_radius + courtyard_margin

            # 创建矩形
            rect = pcbnew.PCB_SHAPE(footprint)
            rect.SetShape(pcbnew.S_RECT)
            rect.SetLayer(pcbnew.F_CrtYd)
            rect.SetWidth(pcbnew.FromMM(0.05))

            rect.SetStart(pcbnew.VECTOR2I(
                pcbnew.FromMM(-x_court),
                pcbnew.FromMM(-y_court)
            ))
            rect.SetEnd(pcbnew.VECTOR2I(
                pcbnew.FromMM(x_court),
                pcbnew.FromMM(y_court)
            ))

            footprint.Add(rect)

            print("已添加BGA Courtyard层")

        except Exception as e:
            print(f"添加BGA禁止布线层错误: {str(e)}")

    def set_status(self, message):
        """设置状态栏文本"""
        self.status_text.SetLabel(message)


class AddParameterDialog(wx.Dialog):
    """添加参数对话框"""

    def __init__(self, parent):
        wx.Dialog.__init__(self, parent, title="添加参数", size=(450, 250))

        # 主sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # 参数名称
        name_sizer = wx.BoxSizer(wx.HORIZONTAL)
        name_label = wx.StaticText(self, label="参数名称:", size=(80, -1))
        name_sizer.Add(name_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.param_name = wx.TextCtrl(self, size=(300, -1))
        name_sizer.Add(self.param_name, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(name_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # 参数数值
        value_sizer = wx.BoxSizer(wx.HORIZONTAL)
        value_label = wx.StaticText(self, label="参数数值:", size=(80, -1))
        value_sizer.Add(value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.param_value = wx.TextCtrl(self, size=(300, -1))
        value_sizer.Add(self.param_value, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(value_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # 参数单位
        unit_sizer = wx.BoxSizer(wx.HORIZONTAL)
        unit_label = wx.StaticText(self, label="参数单位:", size=(80, -1))
        unit_sizer.Add(unit_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.param_unit = wx.TextCtrl(self, value="mm", size=(300, -1))
        unit_sizer.Add(self.param_unit, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(unit_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # 添加一些间距
        main_sizer.AddSpacer(10)

        # 按钮 - 使用标准对话框按钮
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # 设置对话框的sizer
        self.SetSizer(main_sizer)

        # 设置焦点到第一个输入框
        self.param_name.SetFocus()

        # 居中显示
        self.Centre()

# 注册插件
FootprintGeneratorPlugin().register()