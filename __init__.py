"""
KiCad SOIC Footprint Generator Plugin
用于从数据手册自动生成SOIC封装的插件
"""

import pcbnew
import wx
import wx.lib.pdfviewer as pdfviewer
import os
import json
import requests
from pathlib import Path
import sys
import traceback

class SOICFootprintGeneratorPlugin(pcbnew.ActionPlugin):
    """
    KiCad SOIC封装生成插件主类
    """

    def defaults(self):
        print("SOICPlugin: defaults() called")
        try:
            self.name = "SOIC Footprint Generator"
            self.category = "Manufacturing"
            self.description = "从数据手册自动生成SOIC封装"
            self.show_toolbar_button = True
        except Exception as e:
            with open("C:/Log/kicad_plugin_error3.txt", "w") as f:
                f.write(traceback.format_exc())

    def Run(self):
        try:
            import wx
            print("wx imported successfully")
            dialog = SOICGeneratorDialog(None)
            dialog.ShowModal()
            dialog.Destroy()
        except Exception as e:
            with open("C:/Log/kicad_plugin_error2.txt", "w") as f:
                f.write(traceback.format_exc())


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

        self.init_ui()

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
        创建左侧PDF预览面板
        """
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 工具栏
        toolbar_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.upload_btn = wx.Button(panel, label="上传PDF")
        self.upload_btn.Bind(wx.EVT_BUTTON, self.on_upload_pdf)
        toolbar_sizer.Add(self.upload_btn, 0, wx.ALL, 5)

        self.fetch_btn = wx.Button(panel, label="获取解析结果")
        self.fetch_btn.Bind(wx.EVT_BUTTON, self.on_fetch_results)
        self.fetch_btn.Enable(False)
        toolbar_sizer.Add(self.fetch_btn, 0, wx.ALL, 5)

        sizer.Add(toolbar_sizer, 0, wx.EXPAND)

        # PDF预览区域
        try:
            self.pdf_viewer = pdfviewer.pdfViewer(panel, -1, wx.DefaultPosition,
                                                  wx.DefaultSize, wx.HSCROLL | wx.VSCROLL)
            sizer.Add(self.pdf_viewer, 1, wx.EXPAND | wx.ALL, 5)
        except:
            # 如果无法加载PDF查看器，使用文本控件替代
            self.pdf_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.pdf_text.SetValue("PDF查看器不可用\n请先上传PDF文件")
            sizer.Add(self.pdf_text, 1, wx.EXPAND | wx.ALL, 5)
            self.pdf_viewer = None

        # 页面控制
        page_sizer = wx.BoxSizer(wx.HORIZONTAL)

        if self.pdf_viewer:
            self.prev_page_btn = wx.Button(panel, label="上一页")
            self.prev_page_btn.Bind(wx.EVT_BUTTON, self.on_prev_page)
            page_sizer.Add(self.prev_page_btn, 0, wx.ALL, 5)

            self.page_label = wx.StaticText(panel, label="页码: 0/0")
            page_sizer.Add(self.page_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

            self.next_page_btn = wx.Button(panel, label="下一页")
            self.next_page_btn.Bind(wx.EVT_BUTTON, self.on_next_page)
            page_sizer.Add(self.next_page_btn, 0, wx.ALL, 5)

            page_sizer.AddSpacer(20)

            # 缩放控制
            zoom_in_btn = wx.Button(panel, label="放大")
            zoom_in_btn.Bind(wx.EVT_BUTTON, lambda e: self.pdf_viewer.ZoomIn())
            page_sizer.Add(zoom_in_btn, 0, wx.ALL, 5)

            zoom_out_btn = wx.Button(panel, label="缩小")
            zoom_out_btn.Bind(wx.EVT_BUTTON, lambda e: self.pdf_viewer.ZoomOut())
            page_sizer.Add(zoom_out_btn, 0, wx.ALL, 5)

        sizer.Add(page_sizer, 0, wx.EXPAND)

        # 状态栏
        self.status_text = wx.StaticText(panel, label="就绪")
        sizer.Add(self.status_text, 0, wx.EXPAND | wx.ALL, 5)

        panel.SetSizer(sizer)
        return panel

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
        上传PDF处理
        """
        wildcard = "PDF文件 (*.pdf)|*.pdf"
        dialog = wx.FileDialog(self, "选择PDF数据手册", wildcard=wildcard,
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)

        if dialog.ShowModal() == wx.ID_OK:
            self.pdf_path = dialog.GetPath()
            self.load_pdf_preview()
            self.upload_pdf_to_api()

        dialog.Destroy()

    def load_pdf_preview(self):
        """
        加载PDF预览
        """
        if not self.pdf_path or not self.pdf_viewer:
            return

        try:
            self.pdf_viewer.LoadFile(self.pdf_path)
            self.update_page_label()
            self.set_status(f"已加载: {os.path.basename(self.pdf_path)}")
        except Exception as e:
            self.set_status(f"PDF加载失败: {str(e)}")
            if hasattr(self, 'pdf_text'):
                self.pdf_text.SetValue(f"已上传: {os.path.basename(self.pdf_path)}\n\nPDF预览加载失败")

    def update_page_label(self):
        """
        更新页码标签
        """
        if self.pdf_viewer and hasattr(self, 'page_label'):
            current = self.pdf_viewer.GetCurrentPage()
            total = self.pdf_viewer.GetNumPages()
            self.page_label.SetLabel(f"页码: {current}/{total}")

    def on_prev_page(self, event):
        """前一页"""
        if self.pdf_viewer:
            self.pdf_viewer.GotoPreviousPage()
            self.update_page_label()

    def on_next_page(self, event):
        """后一页"""
        if self.pdf_viewer:
            self.pdf_viewer.GotoNextPage()
            self.update_page_label()

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

                    # 启用获取按钮
                    self.fetch_btn.Enable(True)

                    # 自动获取解析结果
                    wx.CallLater(1000, self.fetch_package_data)
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

        self.set_status("正在获取封装参数...")

        try:
            url = f"{self.api_base_url}/{self.datasheet_uuid}"
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                self.package_list = response.json()

                if self.package_list and len(self.package_list) > 0:
                    self.display_all_packages()
                    self.set_status(f"成功获取 {len(self.package_list)} 个封装结果")
                    self.save_generate_btn.Enable(True)
                else:
                    self.set_status("未找到封装数据")
                    wx.MessageBox("请等待后端解析完成", "提示",
                                  wx.OK | wx.ICON_INFORMATION)
            else:
                self.set_status(f"获取失败: HTTP {response.status_code}")
                wx.MessageBox(f"获取失败: {response.text}", "错误", wx.OK | wx.ICON_ERROR)

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

    def create_package_panel(self, package, index):
        """
        为单个封装创建编辑面板
        """
        panel = wx.Panel(self.scroll_window)
        panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 封装基本信息（可编辑）
        info_sizer = wx.FlexGridSizer(3, 2, 5, 10)
        info_sizer.AddGrowableCol(1)

        # 封装类型
        info_sizer.Add(wx.StaticText(panel, label="封装类型:"), 0,
                       wx.ALIGN_CENTER_VERTICAL)
        package_type_ctrl = wx.TextCtrl(panel, value=package.get('packageType', ''))
        package_type_ctrl.SetName(f"packageType_{index}")
        info_sizer.Add(package_type_ctrl, 1, wx.EXPAND)

        # 封装名称
        info_sizer.Add(wx.StaticText(panel, label="封装名称:"), 0,
                       wx.ALIGN_CENTER_VERTICAL)
        package_name_ctrl = wx.TextCtrl(panel, value=package.get('packageName', ''))
        package_name_ctrl.SetName(f"packageName_{index}")
        info_sizer.Add(package_name_ctrl, 1, wx.EXPAND)

        # 页码
        info_sizer.Add(wx.StaticText(panel, label="页码:"), 0,
                       wx.ALIGN_CENTER_VERTICAL)
        page_numbers_ctrl = wx.TextCtrl(panel, value=package.get('pageNumbers', ''))
        page_numbers_ctrl.SetName(f"pageNumbers_{index}")
        info_sizer.Add(page_numbers_ctrl, 1, wx.EXPAND)

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
        添加参数
        """
        dialog = wx.TextEntryDialog(self, "输入参数名称:", "添加参数")
        if dialog.ShowModal() == wx.ID_OK:
            param_name = dialog.GetValue()
            idx = params_list.InsertItem(params_list.GetItemCount(), param_name)
            params_list.SetItem(idx, 1, "")
            params_list.SetItem(idx, 2, "mm")
        dialog.Destroy()

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
                pad_left.SetPosition(pcbnew.wxPointMM(-pad_spacing / 2, y_pos))
                pad_left.SetLayerSet(pad_left.SMDMask())
                footprint.Add(pad_left)

                # 右侧焊盘
                pad_right = pcbnew.PAD(footprint)
                pad_right.SetNumber(str(i + 1 + pins_per_side))
                pad_right.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad_right.SetShape(pcbnew.PAD_SHAPE_RECT)
                pad_right.SetSize(pcbnew.wxSizeMM(pad_length, pad_width))
                pad_right.SetPosition(pcbnew.wxPointMM(pad_spacing / 2, y_pos))
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
            pcbnew.wxPointMM(-length / 2 - margin, -width / 2 - margin),
            pcbnew.wxPointMM(length / 2 + margin, -width / 2 - margin),
            pcbnew.wxPointMM(length / 2 + margin, width / 2 + margin),
            pcbnew.wxPointMM(-length / 2 - margin, width / 2 + margin)
        ]

        for i in range(4):
            line = pcbnew.FP_SHAPE(footprint)
            line.SetShape(pcbnew.S_SEGMENT)
            line.SetStart(pts[i])
            line.SetEnd(pts[(i + 1) % 4])
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


# 注册插件
try:
    SOICFootprintGeneratorPlugin().register()
except Exception as e:
    with open("C:/Log/kicad_plugin_error.txt", "w") as f:
        f.write(traceback.format_exc())