"""
KiCad SOIC Footprint Generator Plugin
用于从数据手册自动生成SOIC封装的插件
"""

import pcbnew
import wx
import os
import json
import requests

class SOICFootprintGeneratorPlugin(pcbnew.ActionPlugin):
    """
    KiCad SOIC封装生成插件主类
    """

    def defaults(self):
        """
        插件的基本信息
        """
        self.name = "SOIC Footprint Generator"
        self.category = "Manufacturing"
        self.description = "从数据手册自动生成SOIC封装"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        """
        插件运行入口
        """
        dialog = SOICGeneratorDialog(None)
        dialog.ShowModal()
        dialog.Destroy()


class SOICGeneratorDialog(wx.Dialog):
    """
    SOIC封装生成器对话框
    """

    def __init__(self, parent):
        wx.Dialog.__init__(self, parent, title="SOIC封装生成器", size=(1400, 900))

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
        params_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_EDIT_LABELS,
                                 size=(-1, 300))
        params_list.SetName(f"params_{index}")

        # 添加列
        params_list.InsertColumn(0, "参数名称", width=250)
        params_list.InsertColumn(1, "数值", width=150)
        params_list.InsertColumn(2, "单位", width=100)

        # 解析并填充参数
        package_result = package.get('packageResult', '{}')
        try:
            params = json.loads(package_result)

            for key, value in params.items():
                idx = params_list.InsertItem(params_list.GetItemCount(), key)
                params_list.SetItem(idx, 1, str(value))
                # 根据参数名判断单位
                unit = self.get_unit_for_param(key)
                params_list.SetItem(idx, 2, unit)

        except Exception as e:
            print(f"解析封装参数失败: {str(e)}")

        sizer.Add(params_list, 1, wx.EXPAND | wx.ALL, 10)

        # 操作按钮
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        add_param_btn = wx.Button(panel, label="添加参数")
        add_param_btn.Bind(wx.EVT_BUTTON,
                          lambda e, pl=params_list: self.on_add_param(e, pl))
        btn_sizer.Add(add_param_btn, 0, wx.ALL, 5)

        del_param_btn = wx.Button(panel, label="删除选中参数")
        del_param_btn.Bind(wx.EVT_BUTTON,
                          lambda e, pl=params_list: self.on_delete_param(e, pl))
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
        if any(x in param_lower for x in ['count', 'orientation', 'direction']):
            return ""
        else:
            return "mm"

    def on_add_param(self, event, params_list):
        """
        添加参数 - 同时输入名称和数值
        """
        # 创建自定义对话框
        dlg = AddParameterDialog(self)

        if dlg.ShowModal() == wx.ID_OK:
            param_name = dlg.param_name.GetValue()
            param_value = dlg.param_value.GetValue()
            param_unit = dlg.param_unit.GetValue()

            if param_name:  # 至少要有参数名
                idx = params_list.InsertItem(params_list.GetItemCount(), param_name)
                params_list.SetItem(idx, 1, param_value)
                params_list.SetItem(idx, 2, param_unit)

        dlg.Destroy()

    def on_delete_param(self, event, params_list):
        """
        删除选中的参数
        """
        selected = params_list.GetFirstSelected()
        if selected >= 0:
            params_list.DeleteItem(selected)

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
                if self.save_package_to_api(package_data, package.get('packageId')):
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

            # 收集参数
            params_list = panel.FindWindowByName(f"params_{index}")
            params = {}
            for i in range(params_list.GetItemCount()):
                key = params_list.GetItemText(i, 0)
                value = params_list.GetItemText(i, 1)
                params[key] = value

            return {
                'packageType': package_type,
                'packageName': package_name,
                'pageNumbers': page_numbers,
                'packageResult': params
            }
        except Exception as e:
            print(f"收集封装数据失败: {str(e)}")
            return None

    def save_package_to_api(self, package_data, package_id):
        """
        保存封装数据到API
        """
        try:
            url = f"{self.api_base_url}/{package_id}"

            payload = {
                'packageType': package_data['packageType'],
                'packageName': package_data['packageName'],
                'pageNumbers': package_data['pageNumbers'],
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

            # 提取必要参数
            pin_count = int(params.get('Pin Count', params.get('PinCount', 8)))
            pitch = float(params.get('Pitch', 1.27))
            pad_length = float(params.get('Foot Length', params.get('FootLength', 0.6)))
            pad_width = float(params.get('Lead Width', params.get('LeadWidth', 0.45)))
            body_length = float(params.get('Package Body Length',
                                         params.get('PackageBodyLength', 4.9)))
            body_width = float(params.get('Package Body Width',
                                        params.get('PackageBodyWidth', 3.9)))
            overall_width = float(params.get('Overall Width',
                                           params.get('OverallWidth', 6.0)))

            # 创建封装
            board = pcbnew.GetBoard()
            footprint = pcbnew.FOOTPRINT(board)
            footprint.SetReference("U**")
            footprint.SetValue(package_name)

            # 设置属性
            footprint.SetAttributes(pcbnew.FP_SMD)

            # 计算焊盘间距
            pins_per_side = pin_count // 2
            pad_spacing = overall_width

            # 生成焊盘
            for i in range(pins_per_side):
                y_pos = (i - (pins_per_side - 1) / 2) * pitch

                # 左侧焊盘
                pad_left = pcbnew.PAD(footprint)
                pad_left.SetNumber(str(i + 1))
                pad_left.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad_left.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad_left.SetSize(pcbnew.wxSizeMM(pad_length, pad_width))
                pad_left.SetPosition(pcbnew.wxPointMM(-pad_spacing/2, y_pos))
                pad_left.SetLayerSet(pad_left.SMDMask())
                footprint.Add(pad_left)

                # 右侧焊盘
                pad_right = pcbnew.PAD(footprint)
                pad_right.SetNumber(str(i + 1 + pins_per_side))
                pad_right.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad_right.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad_right.SetSize(pcbnew.wxSizeMM(pad_length, pad_width))
                pad_right.SetPosition(pcbnew.wxPointMM(pad_spacing/2, y_pos))
                pad_right.SetLayerSet(pad_right.SMDMask())
                footprint.Add(pad_right)

            # 添加外形线
            self.add_courtyard(footprint, body_length, body_width)

            # 保存封装
            self.save_footprint(footprint, package_name)

        except Exception as e:
            wx.MessageBox(f"生成封装错误: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def add_courtyard(self, footprint, length, width):
        """
        添加封装外形
        """
        margin = 0.25
        layer = pcbnew.F_CrtYd
        line_width = pcbnew.FromMM(0.05)

        pts = [
            pcbnew.wxPointMM(-length/2 - margin, -width/2 - margin),
            pcbnew.wxPointMM(length/2 + margin, -width/2 - margin),
            pcbnew.wxPointMM(length/2 + margin, width/2 + margin),
            pcbnew.wxPointMM(-length/2 - margin, width/2 + margin)
        ]

        for i in range(4):
            line = pcbnew.FP_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pts[i])
            line.SetEnd(pts[(i+1) % 4])
            line.SetLayer(layer)
            line.SetWidth(line_width)
            footprint.Add(line)

    def save_footprint(self, footprint, package_name):
        """
        保存封装文件
        """
        wildcard = "KiCad Footprint (*.kicad_mod)|*.kicad_mod"
        default_name = f"{package_name}.kicad_mod"

        dialog = wx.FileDialog(self, "保存封装文件",
                              defaultFile=default_name,
                              wildcard=wildcard,
                              style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)

        if dialog.ShowModal() == wx.ID_OK:
            path = dialog.GetPath()
            footprint.SetFPID(pcbnew.LIB_ID(package_name))

            try:
                io = pcbnew.PCB_IO()
                io.FootprintSave(path, footprint)
                self.set_status(f"封装已保存: {package_name}")
            except:
                with open(path, 'w') as f:
                    f.write(footprint.Format())
                self.set_status(f"封装已保存: {package_name}")

        dialog.Destroy()

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
SOICFootprintGeneratorPlugin().register()