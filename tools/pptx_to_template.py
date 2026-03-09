#!/usr/bin/env python3
"""
PPTX/POTX to Layout Template Converter

将已有的 PPTX 或 POTX 文件转换为符合 layouts 标准的模板文件夹。
完整解析所有要素：画布、配色、排版、字体、页面结构。
"""

import os
import sys
import zipfile
import re
import colorsys
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict


@dataclass
class ThemeColor:
    """主题颜色定义"""
    name: str
    value: str
    is_scheme: bool = False
    display_name: str = ""


@dataclass
class FontScheme:
    """字体方案"""
    typeface: str
    panose: str = ""
    pitch: str = ""
    size: int = 18


@dataclass
class LayoutPlaceholder:
    """版式占位符"""
    type: str
    idx: str
    x: int
    y: int
    cx: int
    cy: int
    name: str = ""


@dataclass
class SlideLayout:
    """幻灯片布局"""
    name: str
    type: str
    cx: int
    cy: int
    placeholders: List[LayoutPlaceholder] = field(default_factory=list)
    background: Optional[str] = None
    is_dark_bg: bool = False


@dataclass
class CanvasInfo:
    """画布信息"""
    width: int
    height: int
    viewBox: str
    aspect_ratio: str
    format_name: str


@dataclass 
class BackgroundStyle:
    """背景样式"""
    color: str = "#FFFFFF"
    is_gradient: bool = False
    gradient_colors: List[str] = field(default_factory=list)
    gradient_angle: int = 45
    is_dark: bool = False


@dataclass
class ExtractedTemplate:
    """提取的模板完整信息"""
    canvas: CanvasInfo
    colors: Dict[str, ThemeColor]
    fonts: Dict[str, FontScheme]
    layouts: Dict[str, SlideLayout]
    backgrounds: Dict[str, BackgroundStyle]


@dataclass
class ShapeGeometry:
    """形状几何信息"""
    x: int
    y: int
    width: int
    height: int
    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    path_data: Optional[str] = None  # For custom paths
    preset: Optional[str] = None     # Preset shape name (roundRect, ellipse, etc.)


@dataclass
class ShapeFill:
    """形状填充样式"""
    type: str = 'solid'  # 'solid', 'gradient', 'pattern', 'picture', 'none'
    color: str = '#000000'
    gradient_colors: List[str] = field(default_factory=list)
    gradient_angle: int = 0
    opacity: float = 1.0
    image_path: Optional[str] = None


@dataclass
class ShapeStroke:
    """形状描边样式"""
    color: str = '#000000'
    width: int = 1
    opacity: float = 1.0
    dash_array: Optional[str] = None  # e.g., "5,5" for dashed line


@dataclass
class ExtractedShape:
    """完整的形状信息"""
    type: str  # 'rect', 'ellipse', 'path', 'line', 'image', 'text', 'group'
    geometry: ShapeGeometry
    fill: ShapeFill
    stroke: ShapeStroke
    z_index: int = 0
    is_placeholder: bool = False
    placeholder_type: Optional[str] = None
    text_content: Optional[str] = None
    group_shapes: List['ExtractedShape'] = field(default_factory=list)  # For grouped shapes


@dataclass
class BackgroundImage:
    """背景图片信息"""
    path: str
    x: int = 0
    y: int = 0
    width: int = 1280
    height: int = 720
    opacity: float = 1.0


@dataclass
class ParsedShape:
    """解析后的形状"""
    name: str
    x: int
    y: int
    width: int
    height: int
    shape_type: str  # rect, ellipse, line, text, path, group
    fill_color: Optional[str] = None
    fill_opacity: float = 1.0
    stroke_color: Optional[str] = None
    stroke_width: int = 0
    text_content: Optional[str] = None
    text_style: Optional[Dict[str, Any]] = None  # font, size, color, bold, align
    is_placeholder: bool = False
    placeholder_type: Optional[str] = None  # title, body, subTitle, etc.
    rotation: float = 0.0
    path_data: Optional[str] = None  # SVG path data for custom shapes
    z_index: int = 0


@dataclass
class ParsedImage:
    """解析后的图片"""
    name: str
    x: int
    y: int
    width: int
    height: int
    image_path: str  # 相对路径，如 images/image1.png
    rId: str = ""  # 关系ID
    opacity: float = 1.0


@dataclass
class ParsedSlide:
    """解析后的幻灯片"""
    index: int  # 1-based
    shapes: List[ParsedShape] = field(default_factory=list)
    images: List[ParsedImage] = field(default_factory=list)
    background: Optional[BackgroundStyle] = None
    layout_idx: int = 0
    page_type: str = "content"  # cover, toc, chapter, content, ending
    raw_xml: Optional[str] = None  # 保存原始XML用于调试


class PPTXToTemplateConverter:
    """PPTX/POTX 文件完整解析与模板生成"""
    
    NS = {
        'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'vt': 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes',
    }
    
    PLACEHOLDER_MAP = {
        'title': '标题',
        'body': '正文',
        'centerTitle': '中心标题',
        'subTitle': '副标题',
        'date': '日期',
        'slideNumber': '页码',
        'footer': '页脚',
        'header': '页眉',
        'sldNum': '幻灯片编号',
        'obj': '对象',
        'pic': '图片',
        'chart': '图表',
        'media': '媒体',
    }
    
    LAYOUT_TYPE_MAP = {
        'title': '标题幻灯片',
        'text': '标题和内容',
        'twoColumn': '两栏内容',
        'sectionHeader': '分节符',
        'subTitle': '副标题',
        'blank': '空白',
        'obj': '对象',
        'pic': '图片',
        'chart': '图表',
        'table': '表格',
        'clipart': '剪贴画',
        'dgm': '图示',
        'media': '媒体',
    }

    PAGE_TYPE_MAP = {
        'cover': ('封面页', '01_cover.svg'),
        'toc': ('目录页', '02_toc.svg'),
        'chapter': ('章节页', '02_chapter.svg'),
        'content': ('内容页', '03_content.svg'),
        'ending': ('结束页', '04_ending.svg'),
    }

    PLACEHOLDER_TYPE_MAP = {
        'title': '{{TITLE}}',
        'body': '{{CONTENT}}',
        'subTitle': '{{SUBTITLE}}',
        'centerTitle': '{{TITLE}}',
        'date': '{{DATE}}',
        'slideNumber': '{{PAGE_NUM}}',
        'sldNum': '{{PAGE_NUM}}',
        'footer': '{{FOOTER}}',
        'header': '{{HEADER}}',
    }
    
    CANVAS_FORMATS = {
        (1280, 720): ("16:9", "标准宽屏"),
        (1024, 768): ("4:3", "标准比例"),
        (960, 540): ("16:9", "小尺寸宽屏"),
        (1440, 810): ("16:9", "MacBook Pro"),
        (1920, 1080): ("16:9", "全高清"),
        (2560, 1440): ("16:9", "2K"),
    }
    
    def __init__(self, input_file: str, output_dir: str = None):
        self.input_file = Path(input_file)
        self.template_name = self._sanitize_name(self.input_file.stem)
        # 默认输出到 templates/layouts/{template_name}/
        self.output_dir = output_dir or f"templates/layouts/{self.template_name}"
        
        self.theme_colors: Dict[str, ThemeColor] = {}
        self.font_scheme: Dict[str, FontScheme] = {}
        self.slide_master: Optional[SlideLayout] = None
        self.slide_layouts: Dict[int, SlideLayout] = {}
        self.slide_count: int = 0
        self.canvas_info: Optional[CanvasInfo] = None
        self.background_styles: Dict[str, BackgroundStyle] = {}
        
        self.slide_master_xml = None
        self.theme_xml = None
        self.presentation_xml = None

        # 新增：解析后的幻灯片数据
        self.parsed_slides: List[ParsedSlide] = []
        self.slide_rels: Dict[str, Dict[str, str]] = {}  # slide rels mapping
        self.media_map: Dict[str, str] = {}  # rId -> image filename

        # 新增：母版图片（背景图、装饰图等）
        self.master_images: List[ParsedImage] = []
        self.master_shapes: List[ParsedShape] = []  # 母版装饰形状
        self.master_rels: Dict[str, str] = {}  # 母版关系映射

        # 新增：版式图片映射 (layout_idx -> List[ParsedImage])
        self.layout_images: Dict[int, List[ParsedImage]] = {}
        self.layout_shapes: Dict[int, List[ParsedShape]] = {}  # 版式形状映射
        self.layout_rels: Dict[str, Dict[str, str]] = {}  # layout关系映射

        self.extracted: Optional[ExtractedTemplate] = None
        
    def _sanitize_name(self, name: str) -> str:
        """清理模板名称"""
        name = re.sub(r'[^\w\u4e00-\u9fff-]', '_', name)
        name = re.sub(r'_+', '_', name)
        return name.strip('_')
    
    def _emu_to_px(self, emu: int, dpi: int = 96) -> int:
        """EMU转像素"""
        return int(emu * dpi / 914400)
    
    def _px_to_emu(self, px: int, dpi: int = 96) -> int:
        """像素转EMU"""
        return int(px * 914400 / dpi)
    
    def convert(self) -> bool:
        """执行完整转换"""
        print(f"[INFO] 输入文件: {self.input_file}")
        print(f"[INFO] 输出目录: {self.output_dir}")
        
        if not self.input_file.exists():
            print(f"[ERROR] 错误: 文件不存在 - {self.input_file}")
            return False
        
        try:
            with zipfile.ZipFile(self.input_file, 'r') as zf:
                print("\n" + "="*60)
                print("[SCAN] 开始解析 PPTX 文件结构...")
                print("="*60)

                self._parse_all(zf)
                self._create_output_directory()

                print("\n" + "="*60)
                print("[LIST] 解析结果汇总")
                print("="*60)
                self._print_extraction_summary()

                print("\n" + "="*60)
                print("[ART] 生成模板文件...")
                print("="*60)

                self._generate_complete_template()
                self._extract_media(zf)

                # 新增：如果有解析的幻灯片，生成幻灯片模板
                if self.parsed_slides:
                    self._generate_slide_templates()
            
            print("\n" + "="*60)
            print("[OK] 模板生成完成!")
            print("="*60)
            print(f"   模板名称: {self.template_name}")
            print(f"   幻灯片数: {self.slide_count}")
            print(f"   画布尺寸: {self.canvas_info.width}x{self.canvas_info.height} ({self.canvas_info.aspect_ratio})")
            print(f"   主题颜色: {len(self.theme_colors)} 个")
            print(f"   字体方案: {len(self.font_scheme)} 个")
            print(f"   页面布局: {len(self.slide_layouts)} 个")
            print(f"   解析幻灯片: {len(self.parsed_slides)} 张")
            print(f"   输出位置: {self.output_dir}/")
            return True
        except Exception as e:
            print(f"[ERROR] 转换失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _parse_all(self, zf: zipfile.ZipFile):
        """完整解析PPTX文件"""
        files = zf.namelist()
        print(f"[PKG] 发现 {len(files)} 个文件")

        self._parse_presentation_xml(zf)
        self._parse_theme(zf)
        self._parse_slide_master(zf)
        self._parse_all_layouts(zf)

        # 新增：解析所有幻灯片内容
        if self.slide_count > 0:
            self._parse_all_slides(zf)
    
    def _parse_presentation_xml(self, zf: zipfile.ZipFile):
        """解析 presentation.xml 获取画布和幻灯片信息"""
        for f in zf.namelist():
            if f.endswith('presentation.xml'):
                try:
                    content = zf.read(f)
                    root = ET.fromstring(content)
                    
                    sldSz = root.find('.//p:sldSz', self.NS)
                    if sldSz is not None:
                        cx = int(sldSz.get('cx', 0))
                        cy = int(sldSz.get('cy', 0))
                        
                        px_width = self._emu_to_px(cx)
                        px_height = self._emu_to_px(cy)
                        
                        aspect = "16:9"
                        format_name = "标准宽屏"
                        for (w, h), (ratio, name) in self.CANVAS_FORMATS.items():
                            if abs(w - px_width) < 100:
                                aspect = ratio
                                format_name = name
                                break
                        
                        self.canvas_info = CanvasInfo(
                            width=px_width,
                            height=px_height,
                            viewBox=f"0 0 {px_width} {px_height}",
                            aspect_ratio=aspect,
                            format_name=format_name
                        )
                        print(f"[SIZE] 画布尺寸: {px_width}x{px_height} ({aspect})")
                    
                    sldIdLst = root.find('.//p:sldIdLst', self.NS)
                    if sldIdLst is not None:
                        slides = sldIdLst.findall('.//p:sldId', self.NS)
                        self.slide_count = len(slides)
                        print(f"[DATA] 幻灯片数量: {self.slide_count}")
                        
                except Exception as e:
                    print(f"[WARN]  解析 presentation.xml 失败: {e}")
        
        if not self.canvas_info:
            self.canvas_info = CanvasInfo(1280, 720, "0 0 1280 720", "16:9", "标准宽屏")
            print("[WARN]  未找到画布信息，使用默认 1280x720")
    
    def _parse_theme(self, zf: zipfile.ZipFile):
        """解析主题文件 (theme/theme1.xml)"""
        for f in zf.namelist():
            if 'theme/theme' in f and f.endswith('.xml'):
                try:
                    self.theme_xml = zf.read(f)
                    root = ET.fromstring(self.theme_xml)
                    
                    print(f"\n[ART] 解析主题文件: {f}")
                    
                    self._extract_colors_from_theme(root)
                    self._extract_fonts_from_theme(root)
                    
                    return
                except Exception as e:
                    print(f"[WARN]  解析主题失败: {e}")
        
        print("[WARN]  未找到主题文件，使用默认配色")
        self._use_default_theme()
    
    def _extract_colors_from_theme(self, root: ET.Element):
        """从主题XML提取颜色"""
        color_scheme = root.find('.//a:clrScheme', self.NS)
        if color_scheme is None:
            return
        
        color_names = {
            'dk1': '文字/背景 - 深色 1',
            'lt1': '文字/背景 - 浅色 1',
            'dk2': '文字/背景 - 深色 2',
            'lt2': '文字/背景 - 浅色 2',
            'accent1': '强调文字颜色 1',
            'accent2': '强调文字颜色 2',
            'accent3': '强调文字颜色 3',
            'accent4': '强调文字颜色 4',
            'accent5': '强调文字颜色 5',
            'accent6': '强调文字颜色 6',
            'hlink': '超链接',
            'folHlink': '已访问的超链接',
            'bg1': '背景 - 浅色',
            'bg2': '背景 - 深色',
        }
        
        for elem in color_scheme:
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag in color_names:
                color = self._parse_color_from_element(elem)
                if color:
                    color.display_name = color_names[tag]
                    self.theme_colors[tag] = color
        
        print(f"   提取到 {len(self.theme_colors)} 个主题颜色")
        
        for name, color in self.theme_colors.items():
            print(f"   - {color.display_name}: {color.value}")
    
    def _parse_color_from_element(self, elem) -> Optional[ThemeColor]:
        """解析颜色元素，包括亮度修正器"""
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

        # 首先尝试sRGB颜色（直接RGB值）
        srgb = elem.find('.//a:srgbClr', self.NS)
        if srgb is not None:
            val = srgb.get('val')
            if val:
                # 检查是否有亮度修正器
                modifiers = {}
                lumMod = srgb.find('.//a:lumMod', self.NS)
                if lumMod is not None:
                    modifiers['lumMod'] = int(lumMod.get('val', '100000'))
                lumOff = srgb.find('.//a:lumOff', self.NS)
                if lumOff is not None:
                    modifiers['lumOff'] = int(lumOff.get('val', '0'))

                # 应用修正器
                if modifiers:
                    base_color = f"#{val}"
                    return ThemeColor(
                        name=tag,
                        value=self._resolve_scheme_color('', modifiers) if not base_color else self._apply_color_modifiers(base_color, modifiers),
                        is_scheme=False
                    )
                return ThemeColor(name=tag, value=f"#{val}", is_scheme=False)

        # 尝试方案颜色（主题色引用）
        scheme = elem.find('.//a:schemeClr', self.NS)
        if scheme is not None:
            val = scheme.get('val')
            if val:
                # 提取亮度修正器
                modifiers = {}
                lumMod = scheme.find('.//a:lumMod', self.NS)
                if lumMod is not None:
                    modifiers['lumMod'] = int(lumMod.get('val', '100000'))
                lumOff = scheme.find('.//a:lumOff', self.NS)
                if lumOff is not None:
                    modifiers['lumOff'] = int(lumOff.get('val', '0'))

                # 立即解析为实际颜色
                if modifiers:
                    return ThemeColor(
                        name=tag,
                        value=self._resolve_scheme_color(val, modifiers),
                        is_scheme=False
                    )
                else:
                    # 保存为scheme引用，稍后解析
                    return ThemeColor(name=tag, value=f"[scheme:{val}]", is_scheme=True)

        return None

    def _apply_color_modifiers(self, hex_color: str, modifiers: Dict[str, int]) -> str:
        """应用颜色修正器到HEX颜色"""
        try:
            r, g, b = self._hex_to_rgb(hex_color)
            h, l, s = colorsys.rgb_to_hls(r/255.0, g/255.0, b/255.0)

            if 'lumMod' in modifiers:
                l *= modifiers['lumMod'] / 100000.0
            if 'lumOff' in modifiers:
                l += modifiers['lumOff'] / 100000.0

            l = max(0.0, min(1.0, l))
            r, g, b = colorsys.hls_to_rgb(h, l, s)
            return self._rgb_to_hex(int(r*255), int(g*255), int(b*255))
        except:
            return hex_color
    
    def _extract_fonts_from_theme(self, root: ET.Element):
        """从主题XML提取字体"""
        font_scheme = root.find('.//a:fontScheme', self.NS)
        if font_scheme is None:
            return
        
        font_names = {
            'majorFont': '标题字体',
            'minorFont': '正文字体',
            'bodyFont': 'Body字体',
        }
        
        font_size_map = {
            'majorFont': 48,
            'minorFont': 18,
            'bodyFont': 16,
        }
        
        for elem in font_scheme:
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag in font_names:
                latin = elem.find('.//a:latin', self.NS)
                if latin is not None:
                    typeface = latin.get('typeface', 'Arial')
                    panose = latin.get('panose', '')
                    pitch = latin.get('pitchFamily', '')
                    size = font_size_map.get(tag, 18)
                    self.font_scheme[tag] = FontScheme(
                        typeface=typeface,
                        panose=panose,
                        pitch=pitch,
                        size=size
                    )
        
        if self.font_scheme:
            print(f"   提取到 {len(self.font_scheme)} 个字体方案")
            for name, font in self.font_scheme.items():
                print(f"   - {font_names.get(name, name)}: {font.typeface} ({font.size}px)")
    
    def _use_default_theme(self):
        """使用默认主题"""
        self.theme_colors = {
            'dk1': ThemeColor('dk1', '#333333', False, '文字/背景 - 深色 1'),
            'lt1': ThemeColor('lt1', '#FFFFFF', False, '文字/背景 - 浅色 1'),
            'accent1': ThemeColor('accent1', '#4285F4', False, '强调文字颜色 1'),
            'accent2': ThemeColor('accent2', '#EA4335', False, '强调文字颜色 2'),
            'accent3': ThemeColor('accent3', '#FBBC04', False, '强调文字颜色 3'),
            'bg1': ThemeColor('bg1', '#FFFFFF', False, '背景 - 浅色'),
        }
        self.font_scheme = {
            'majorFont': FontScheme('Microsoft YaHei', size=48),
            'minorFont': FontScheme('Microsoft YaHei', size=18),
        }
        print("   使用默认主题配色和字体")
    
    def _parse_slide_master(self, zf: zipfile.ZipFile):
        """解析母版 (slideMaster)"""
        # 首先解析母版关系文件
        self._parse_master_rels(zf)

        for f in zf.namelist():
            if 'slideMasters/slideMaster' in f and f.endswith('.xml'):
                try:
                    content = zf.read(f)
                    root = ET.fromstring(content)

                    # 根元素本身就是 sldMaster
                    sldMaster = root
                    root_tag = root.tag.split('}')[-1] if '}' in root.tag else ''
                    if root_tag != 'sldMaster':
                        # 尝试查找子元素
                        sldMaster = root.find('.//p:sldMaster', self.NS)
                        if sldMaster is None:
                            continue

                    self.slide_master = SlideLayout(
                        name="Slide Master",
                        type="master",
                        cx=0, cy=0,
                        placeholders=[]
                    )

                    bg = sldMaster.find('.//p:bg', self.NS)
                    if bg is not None:
                        bg_color = self._parse_background(bg)
                        self.slide_master.background = bg_color
                        self.slide_master.is_dark_bg = bg_color.is_dark if bg_color else False

                    cSld = sldMaster.find('.//p:cSld', self.NS)
                    if cSld is not None:
                        spTree = cSld.find('.//p:spTree', self.NS)
                        if spTree is not None:
                            self._extract_placeholders_from_tree(spTree, self.slide_master)
                            # 解析母版中的图片和装饰形状
                            self._parse_master_elements(spTree)

                    print(f"[SIZE] 母版解析: {len(self.slide_master.placeholders)} 个占位符, {len(self.master_images)} 张图片, {len(self.master_shapes)} 个装饰形状")
                    return
                except Exception as e:
                    print(f"[WARN]  解析母版失败: {e}")

    def _parse_master_rels(self, zf: zipfile.ZipFile):
        """解析母版关系文件"""
        for f in zf.namelist():
            if 'slideMasters/_rels/slideMaster' in f and f.endswith('.xml.rels'):
                try:
                    content = zf.read(f)
                    root = ET.fromstring(content)

                    for rel in root.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                        rId = rel.get('Id', '')
                        target = rel.get('Target', '')
                        self.master_rels[rId] = target
                except Exception as e:
                    pass

    def _parse_master_elements(self, spTree: ET.Element):
        """解析母版中的图片和装饰形状"""
        z_index = 0
        for elem in spTree:
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

            if tag == 'pic':
                # 解析母版图片
                img = self._parse_master_pic_element(elem, z_index)
                if img:
                    self.master_images.append(img)
                    z_index += 1
            elif tag == 'sp':
                # 解析母版形状（非占位符的装饰形状）
                shape = self._parse_shape_element(elem, 0, z_index)
                if shape and not shape.is_placeholder:
                    # 只保留有填充颜色的装饰形状
                    if shape.fill_color or shape.text_content:
                        self.master_shapes.append(shape)
                        z_index += 1

    def _parse_master_pic_element(self, elem: ET.Element, z_index: int = 0) -> Optional[ParsedImage]:
        """解析母版中的图片元素"""
        try:
            nvPicPr = elem.find('.//p:nvPicPr', self.NS)
            if nvPicPr is None:
                return None

            cNvPr = nvPicPr.find('.//p:cNvPr', self.NS)
            name = cNvPr.get('name', '') if cNvPr is not None else ''

            # 获取几何信息
            geometry = self._parse_shape_geometry(elem)
            if geometry is None:
                return None

            # 获取图片关系ID
            blip = elem.find('.//a:blip', self.NS)
            if blip is None:
                return None

            rId = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed', '')
            if not rId:
                rId = blip.get('r:embed', '')

            # 从母版关系映射获取图片路径
            image_path = ""
            if rId in self.master_rels:
                target = self.master_rels[rId]
                if target.startswith('../media/'):
                    media_name = target.replace('../media/', '')
                    image_path = f"images/{media_name}"

            return ParsedImage(
                name=name,
                x=geometry.x,
                y=geometry.y,
                width=geometry.width,
                height=geometry.height,
                image_path=image_path,
                rId=rId
            )
        except Exception as e:
            return None
    
    def _extract_placeholders_from_tree(self, spTree: ET.Element, layout: SlideLayout):
        """从形状树提取占位符"""
        for elem in spTree:
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag == 'sp':
                ph = self._extract_single_placeholder(elem)
                if ph:
                    layout.placeholders.append(ph)
            elif tag == 'grpSp':
                for child in elem:
                    if child.tag.endswith('}sp'):
                        ph = self._extract_single_placeholder(child)
                        if ph:
                            layout.placeholders.append(ph)
    
    def _extract_single_placeholder(self, elem) -> Optional[LayoutPlaceholder]:
        """提取单个占位符"""
        nvSpPr = elem.find('.//p:nvSpPr', self.NS)
        if nvSpPr is None:
            return None

        cNvPr = nvSpPr.find('.//p:cNvPr', self.NS)
        if cNvPr is None:
            return None

        name = cNvPr.get('name', '')

        ph = cNvPr.find('.//p:ph', self.NS)
        if ph is None:
            return None

        ph_type = ph.get('type', 'body')
        idx = ph.get('idx', '0')

        xfrm = elem.find('.//p:xfrm', self.NS) or elem.find('.//a:xfrm', self.NS)
        if xfrm is None:
            return None

        off = xfrm.find('.//a:off', self.NS)
        ext = xfrm.find('.//a:ext', self.NS)
        if off is None or ext is None:
            return None

        x = self._emu_to_px(int(off.get('x', 0)))
        y = self._emu_to_px(int(off.get('y', 0)))
        cx = self._emu_to_px(int(ext.get('cx', 0)))
        cy = self._emu_to_px(int(ext.get('cy', 0)))

        return LayoutPlaceholder(
            type=ph_type,
            idx=idx,
            x=x, y=y, cx=cx, cy=cy,
            name=name
        )

    def _parse_shape_geometry(self, elem: ET.Element) -> Optional[ShapeGeometry]:
        """解析形状几何信息（位置、尺寸、旋转等）"""
        xfrm = elem.find('.//p:xfrm', self.NS) or elem.find('.//a:xfrm', self.NS)
        if xfrm is None:
            return None

        # 提取位置
        off = xfrm.find('.//a:off', self.NS)
        if off is None:
            return None
        x = self._emu_to_px(int(off.get('x', 0)))
        y = self._emu_to_px(int(off.get('y', 0)))

        # 提取尺寸
        ext = xfrm.find('.//a:ext', self.NS)
        if ext is None:
            return None
        width = self._emu_to_px(int(ext.get('cx', 0)))
        height = self._emu_to_px(int(ext.get('cy', 0)))

        # 提取旋转角度
        rotation = float(xfrm.get('rot', 0)) / 60000.0  # EMU角度转度数

        # 提取翻转信息
        flip_h = xfrm.get('flipH', '0') == '1'
        flip_v = xfrm.get('flipV', '0') == '1'

        # 检查预设几何类型
        preset = None
        prstGeom = elem.find('.//a:prstGeom', self.NS)
        if prstGeom is not None:
            preset = prstGeom.get('prst', 'rect')

        # 检查自定义路径
        path_data = None
        custGeom = elem.find('.//a:custGeom', self.NS)
        if custGeom is not None:
            # TODO: 解析自定义路径
            pass

        return ShapeGeometry(
            x=x, y=y,
            width=width, height=height,
            rotation=rotation,
            flip_h=flip_h, flip_v=flip_v,
            path_data=path_data,
            preset=preset
        )

    def _parse_shape_fill(self, elem: ET.Element) -> ShapeFill:
        """解析形状填充样式"""
        spPr = elem.find('.//p:spPr', self.NS)
        if spPr is None:
            return ShapeFill(type='none')

        # 检查无填充
        noFill = spPr.find('.//a:noFill', self.NS)
        if noFill is not None:
            return ShapeFill(type='none')

        # 检查纯色填充
        solidFill = spPr.find('.//a:solidFill', self.NS)
        if solidFill is not None:
            color = '#000000'
            opacity = 1.0

            # sRGB颜色
            srgbClr = solidFill.find('.//a:srgbClr', self.NS)
            if srgbClr is not None:
                val = srgbClr.get('val')
                if val:
                    color = f"#{val}"
                    # 检查透明度
                    alpha = srgbClr.find('.//a:alpha', self.NS)
                    if alpha is not None:
                        opacity = int(alpha.get('val', '100000')) / 100000.0

            # 方案颜色
            schemeClr = solidFill.find('.//a:schemeClr', self.NS)
            if schemeClr is not None:
                val = schemeClr.get('val')
                if val:
                    # 提取亮度修正器
                    modifiers = {}
                    lumMod = schemeClr.find('.//a:lumMod', self.NS)
                    if lumMod is not None:
                        modifiers['lumMod'] = int(lumMod.get('val', '100000'))
                    lumOff = schemeClr.find('.//a:lumOff', self.NS)
                    if lumOff is not None:
                        modifiers['lumOff'] = int(lumOff.get('val', '0'))

                    # 解析颜色
                    color = self._resolve_scheme_color(val, modifiers if modifiers else None)

                    # 检查透明度
                    alpha = schemeClr.find('.//a:alpha', self.NS)
                    if alpha is not None:
                        opacity = int(alpha.get('val', '100000')) / 100000.0

            return ShapeFill(type='solid', color=color, opacity=opacity)

        # 检查渐变填充
        gradFill = spPr.find('.//a:gradFill', self.NS)
        if gradFill is not None:
            gradient_colors = []
            gsLst = gradFill.find('.//a:gsLst', self.NS)
            if gsLst is not None:
                for gs in gsLst.findall('.//a:gs', self.NS):
                    srgbClr = gs.find('.//a:srgbClr', self.NS)
                    if srgbClr is not None:
                        val = srgbClr.get('val')
                        if val:
                            gradient_colors.append(f"#{val}")

            # 渐变角度
            angle = 0
            lin = gradFill.find('.//a:lin', self.NS)
            if lin is not None:
                angle = int(lin.get('ang', 0)) // 60000  # 转换为度数

            if gradient_colors:
                return ShapeFill(
                    type='gradient',
                    color=gradient_colors[0],  # 主色
                    gradient_colors=gradient_colors,
                    gradient_angle=angle
                )

        # 默认白色填充
        return ShapeFill(type='solid', color='#FFFFFF', opacity=1.0)

    def _parse_shape_stroke(self, elem: ET.Element) -> ShapeStroke:
        """解析形状描边样式"""
        spPr = elem.find('.//p:spPr', self.NS)
        if spPr is None:
            return ShapeStroke(color='none', width=0)

        ln = spPr.find('.//a:ln', self.NS)
        if ln is None:
            return ShapeStroke(color='none', width=0)

        # 描边宽度
        width = self._emu_to_px(int(ln.get('w', 0)))

        # 描边颜色
        color = '#000000'
        opacity = 1.0

        solidFill = ln.find('.//a:solidFill', self.NS)
        if solidFill is not None:
            srgbClr = solidFill.find('.//a:srgbClr', self.NS)
            if srgbClr is not None:
                val = srgbClr.get('val')
                if val:
                    color = f"#{val}"

            schemeClr = solidFill.find('.//a:schemeClr', self.NS)
            if schemeClr is not None:
                val = schemeClr.get('val')
                if val:
                    modifiers = {}
                    lumMod = schemeClr.find('.//a:lumMod', self.NS)
                    if lumMod is not None:
                        modifiers['lumMod'] = int(lumMod.get('val', '100000'))
                    color = self._resolve_scheme_color(val, modifiers if modifiers else None)

        # 虚线样式
        dash_array = None
        prstDash = ln.find('.//a:prstDash', self.NS)
        if prstDash is not None:
            dash_type = prstDash.get('val', 'solid')
            if dash_type == 'dash':
                dash_array = '5,5'
            elif dash_type == 'dot':
                dash_array = '2,2'
            elif dash_type == 'dashDot':
                dash_array = '5,2,2,2'

        return ShapeStroke(color=color, width=width, opacity=opacity, dash_array=dash_array)
    
    def _parse_background(self, bg_elem) -> Optional[BackgroundStyle]:
        """解析背景"""
        bg = BackgroundStyle()
        
        solidFill = bg_elem.find('.//a:solidFill', self.NS)
        if solidFill is not None:
            srgb = solidFill.find('.//a:srgbClr', self.NS)
            if srgb is not None:
                val = srgb.get('val')
                if val:
                    bg.color = f"#{val}"
        
        gradFill = bg_elem.find('.//a:gradFill', self.NS)
        if gradFill is not None:
            gsLst = gradFill.find('.//a:gsLst', self.NS)
            if gsLst is not None:
                for gs in gsLst.findall('.//a:gs', self.NS):
                    srgb = gs.find('.//a:srgbClr', self.NS)
                    if srgb is not None:
                        val = srgb.get('val')
                        if val:
                            bg.gradient_colors.append(f"#{val}")
                bg.is_gradient = bool(bg.gradient_colors)
        
        if bg.gradient_colors:
            bg.color = bg.gradient_colors[0]
        
        bg.is_dark = self._is_dark_color(bg.color)
        
        return bg
    
    def _parse_all_layouts(self, zf: zipfile.ZipFile):
        """解析所有幻灯片布局"""
        # 首先解析布局关系文件
        self._parse_layout_rels(zf)

        layout_map = {}
        layout_idx_map = {}  # layout文件名 -> idx

        for f in zf.namelist():
            if 'slideLayouts/slideLayout' in f and f.endswith('.xml'):
                try:
                    content = zf.read(f)
                    root = ET.fromstring(content)

                    # 根元素可能就是 sldLayout
                    sldLayout = root
                    root_tag = root.tag.split('}')[-1] if '}' in root.tag else ''
                    if root_tag != 'sldLayout':
                        sldLayout = root.find('.//p:sldLayout', self.NS)
                        if sldLayout is None:
                            continue

                    name = sldLayout.get('name', 'Layout')
                    type_attr = sldLayout.get('type', '')

                    layout = SlideLayout(
                        name=name,
                        type=type_attr,
                        cx=0, cy=0,
                        placeholders=[]
                    )

                    bg = sldLayout.find('.//p:bg', self.NS)
                    if bg is not None:
                        bg_style = self._parse_background(bg)
                        layout.background = bg_style.color
                        layout.is_dark_bg = bg_style.is_dark if bg_style else False

                    # 解析布局中的图片和形状
                    layout_file_name = f.split('/')[-1].replace('.xml', '')  # slideLayout1
                    layout_images = []
                    layout_shapes = []

                    cSld = sldLayout.find('.//p:cSld', self.NS)
                    if cSld is not None:
                        spTree = cSld.find('.//p:spTree', self.NS)
                        if spTree is not None:
                            self._extract_placeholders_from_tree(spTree, layout)
                            # 解析布局中的图片和形状
                            z_index = 0
                            for elem in spTree:
                                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                                if tag == 'pic':
                                    img = self._parse_layout_pic_element(elem, layout_file_name, z_index)
                                    if img:
                                        layout_images.append(img)
                                        z_index += 1
                                elif tag == 'sp':
                                    # 解析布局中的形状（非占位符）
                                    shape = self._parse_shape_element(elem, 0, z_index)
                                    if shape and not shape.is_placeholder:
                                        layout_shapes.append(shape)
                                        z_index += 1

                    idx = len(layout_map)
                    layout_map[idx] = layout
                    layout_idx_map[layout_file_name] = idx

                    # 保存布局图片和形状
                    if layout_images:
                        self.layout_images[idx] = layout_images
                    if layout_shapes:
                        self.layout_shapes[idx] = layout_shapes

                except Exception as e:
                    pass

        self.slide_layouts = layout_map
        self._layout_idx_map = layout_idx_map  # 用于后续查找
        total_images = sum(len(imgs) for imgs in self.layout_images.values())
        total_shapes = sum(len(shapes) for shapes in self.layout_shapes.values())
        print(f"[LIST] 解析到 {len(self.slide_layouts)} 个版式布局, {total_images} 张布局图片, {total_shapes} 个布局形状")

    def _parse_layout_rels(self, zf: zipfile.ZipFile):
        """解析布局关系文件"""
        for f in zf.namelist():
            if 'slideLayouts/_rels/slideLayout' in f and f.endswith('.xml.rels'):
                try:
                    content = zf.read(f)
                    root = ET.fromstring(content)

                    layout_match = f.split('/')[-1].replace('.xml.rels', '')
                    rels = {}

                    for rel in root.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                        rId = rel.get('Id', '')
                        target = rel.get('Target', '')
                        rels[rId] = target

                    self.layout_rels[layout_match] = rels
                except Exception as e:
                    pass

    def _parse_layout_pic_element(self, elem: ET.Element, layout_name: str, z_index: int = 0) -> Optional[ParsedImage]:
        """解析布局中的图片元素"""
        try:
            nvPicPr = elem.find('.//p:nvPicPr', self.NS)
            if nvPicPr is None:
                return None

            cNvPr = nvPicPr.find('.//p:cNvPr', self.NS)
            name = cNvPr.get('name', '') if cNvPr is not None else ''

            # 获取几何信息
            geometry = self._parse_shape_geometry(elem)
            if geometry is None:
                return None

            # 获取图片关系ID
            blip = elem.find('.//a:blip', self.NS)
            if blip is None:
                return None

            rId = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed', '')
            if not rId:
                rId = blip.get('r:embed', '')

            # 从布局关系映射获取图片路径
            image_path = ""
            if layout_name in self.layout_rels and rId in self.layout_rels[layout_name]:
                target = self.layout_rels[layout_name][rId]
                if target.startswith('../media/'):
                    media_name = target.replace('../media/', '')
                    image_path = f"images/{media_name}"

            return ParsedImage(
                name=name,
                x=geometry.x,
                y=geometry.y,
                width=geometry.width,
                height=geometry.height,
                image_path=image_path,
                rId=rId
            )
        except Exception as e:
            return None

    def _parse_all_slides(self, zf: zipfile.ZipFile):
        """解析所有幻灯片内容"""
        print(f"\n[SLIDE] 开始解析幻灯片内容...")

        # 1. 解析幻灯片关系文件
        self._parse_slide_rels(zf)

        # 2. 解析媒体文件映射
        self._parse_media_map(zf)

        # 3. 找到所有幻灯片文件
        slide_files = []
        for f in zf.namelist():
            if f.startswith('ppt/slides/slide') and f.endswith('.xml'):
                # 提取幻灯片编号
                match = re.search(r'slide(\d+)\.xml', f)
                if match:
                    slide_num = int(match.group(1))
                    slide_files.append((slide_num, f))

        slide_files.sort(key=lambda x: x[0])

        print(f"[SLIDE] 发现 {len(slide_files)} 张幻灯片")

        # 4. 解析每张幻灯片
        for slide_num, slide_path in slide_files:
            try:
                slide = self._parse_single_slide(zf, slide_path, slide_num)
                self.parsed_slides.append(slide)
            except Exception as e:
                print(f"[WARN]  解析幻灯片 {slide_num} 失败: {e}")

        # 5. 识别页面类型
        total = len(self.parsed_slides)
        for slide in self.parsed_slides:
            slide.page_type = self._detect_page_type(slide, slide.index, total)

        # 6. 打印解析结果
        self._print_slide_summary()

    def _parse_slide_rels(self, zf: zipfile.ZipFile):
        """解析幻灯片关系文件"""
        for f in zf.namelist():
            if 'slides/_rels/slide' in f and f.endswith('.xml.rels'):
                try:
                    content = zf.read(f)
                    root = ET.fromstring(content)

                    slide_match = re.search(r'slide(\d+)\.xml\.rels', f)
                    if not slide_match:
                        continue
                    slide_num = slide_match.group(1)

                    rels = {}
                    for rel in root.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                        rId = rel.get('Id', '')
                        target = rel.get('Target', '')
                        rels[rId] = target

                    self.slide_rels[slide_num] = rels
                except Exception as e:
                    pass

    def _parse_media_map(self, zf: zipfile.ZipFile):
        """创建媒体文件映射"""
        media_files = [f for f in zf.namelist() if f.startswith('ppt/media/')]
        for f in media_files:
            filename = Path(f).name
            # 保存相对路径，用于SVG引用
            self.media_map[f] = f"images/{filename}"

    def _parse_single_slide(self, zf: zipfile.ZipFile, slide_path: str, slide_num: int) -> ParsedSlide:
        """解析单张幻灯片"""
        content = zf.read(slide_path)
        root = ET.fromstring(content)

        slide = ParsedSlide(index=slide_num)

        # 找到 sld 元素
        sld = root.find('.//p:sld', self.NS)
        if sld is None:
            sld = root

        # 解析背景
        bg = sld.find('.//p:bg', self.NS)
        if bg is not None:
            slide.background = self._parse_background(bg)

        # 从幻灯片关系获取布局索引
        slide_num_str = str(slide_num)
        if slide_num_str in self.slide_rels:
            rels = self.slide_rels[slide_num_str]
            for rId, target in rels.items():
                if 'slideLayout' in target:
                    # 从目标路径提取布局名称
                    layout_name = target.split('/')[-1].replace('.xml', '')
                    if hasattr(self, '_layout_idx_map') and layout_name in self._layout_idx_map:
                        slide.layout_idx = self._layout_idx_map[layout_name]
                    break

        # 解析形状树
        cSld = sld.find('.//p:cSld', self.NS)
        if cSld is not None:
            spTree = cSld.find('.//p:spTree', self.NS)
            if spTree is not None:
                z_index = 0
                for elem in spTree:
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

                    if tag == 'sp':  # 形状
                        shape = self._parse_shape_element(elem, slide_num, z_index)
                        if shape:
                            slide.shapes.append(shape)
                            z_index += 1
                    elif tag == 'pic':  # 图片
                        img = self._parse_pic_element(elem, slide_num, z_index)
                        if img:
                            slide.images.append(img)
                            z_index += 1
                    elif tag == 'grpSp':  # 组合形状
                        shapes = self._parse_group_element(elem, slide_num, z_index)
                        slide.shapes.extend(shapes)
                        z_index += len(shapes)

        return slide

    def _parse_shape_element(self, elem: ET.Element, slide_num: int, z_index: int = 0) -> Optional[ParsedShape]:
        """解析单个形状元素"""
        try:
            # 获取名称
            nvSpPr = elem.find('.//p:nvSpPr', self.NS)
            name = ""
            is_placeholder = False
            placeholder_type = None

            if nvSpPr is not None:
                cNvPr = nvSpPr.find('.//p:cNvPr', self.NS)
                if cNvPr is not None:
                    name = cNvPr.get('name', '')

                    # 检查是否隐藏 - 过滤掉隐藏的元素（如水印）
                    hidden = cNvPr.get('hidden', '0')
                    if hidden == '1' or hidden.lower() == 'true':
                        return None

                # 检查是否为占位符
                nvPr = nvSpPr.find('.//p:nvPr', self.NS)
                if nvPr is not None:
                    ph = nvPr.find('.//p:ph', self.NS)
                    if ph is not None:
                        is_placeholder = True
                        placeholder_type = ph.get('type', 'body')

            # 解析几何信息
            geometry = self._parse_shape_geometry(elem)
            if geometry is None:
                return None

            # 过滤掉画布外的元素（可能是隐藏的水印）
            if geometry.x < -10 or geometry.y < -10:
                return None

            # 解析填充
            fill = self._parse_shape_fill(elem)

            # 解析描边
            stroke = self._parse_shape_stroke(elem)

            # 解析文本
            text_content, text_style = self._parse_text_from_shape(elem)

            # 确定形状类型
            shape_type = 'rect'
            if geometry.preset:
                preset_map = {
                    'rect': 'rect',
                    'roundRect': 'rect',
                    'ellipse': 'ellipse',
                    'ellipseNoNv': 'ellipse',
                    'triangle': 'path',
                    'rtTriangle': 'path',
                    'diamond': 'path',
                    'parallelogram': 'path',
                    'trapezoid': 'path',
                    'pentagon': 'path',
                    'hexagon': 'path',
                    'heptagon': 'path',
                    'octagon': 'path',
                    'star4': 'path',
                    'star5': 'path',
                    'star6': 'path',
                    'line': 'line',
                    'straightConnector1': 'line',
                    'bentConnector3': 'path',
                    'curvedConnector3': 'path',
                }
                shape_type = preset_map.get(geometry.preset, 'path')

            if text_content:
                shape_type = 'text'

            return ParsedShape(
                name=name,
                x=geometry.x,
                y=geometry.y,
                width=geometry.width,
                height=geometry.height,
                shape_type=shape_type,
                fill_color=fill.color if fill.type != 'none' else None,
                fill_opacity=fill.opacity,
                stroke_color=stroke.color if stroke.width > 0 else None,
                stroke_width=stroke.width,
                text_content=text_content,
                text_style=text_style,
                is_placeholder=is_placeholder,
                placeholder_type=placeholder_type,
                rotation=geometry.rotation,
                path_data=geometry.path_data,
                z_index=z_index
            )
        except Exception as e:
            return None

    def _parse_pic_element(self, elem: ET.Element, slide_num: int, z_index: int = 0) -> Optional[ParsedImage]:
        """解析图片元素"""
        try:
            nvPicPr = elem.find('.//p:nvPicPr', self.NS)
            if nvPicPr is None:
                return None

            cNvPr = nvPicPr.find('.//p:cNvPr', self.NS)
            name = cNvPr.get('name', '') if cNvPr is not None else ''

            # 获取几何信息
            geometry = self._parse_shape_geometry(elem)
            if geometry is None:
                return None

            # 获取图片关系ID
            blip = elem.find('.//a:blip', self.NS)
            if blip is None:
                return None

            rId = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed', '')
            if not rId:
                rId = blip.get('r:embed', '')

            # 从关系映射获取图片路径
            image_path = ""
            slide_num_str = str(slide_num)
            if slide_num_str in self.slide_rels and rId in self.slide_rels[slide_num_str]:
                target = self.slide_rels[slide_num_str][rId]
                # 媒体文件路径转换为输出路径
                if target.startswith('../media/'):
                    media_name = target.replace('../media/', '')
                    image_path = f"images/{media_name}"

            return ParsedImage(
                name=name,
                x=geometry.x,
                y=geometry.y,
                width=geometry.width,
                height=geometry.height,
                image_path=image_path,
                rId=rId
            )
        except Exception as e:
            return None

    def _parse_group_element(self, elem: ET.Element, slide_num: int, base_z_index: int = 0) -> List[ParsedShape]:
        """解析组合形状"""
        shapes = []
        z_index = base_z_index

        for child in elem:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag

            if tag == 'sp':
                shape = self._parse_shape_element(child, slide_num, z_index)
                if shape:
                    shapes.append(shape)
                    z_index += 1
            elif tag == 'grpSp':
                # 递归处理嵌套组合
                shapes.extend(self._parse_group_element(child, slide_num, z_index))

        return shapes

    def _parse_text_from_shape(self, elem: ET.Element) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """从形状中提取文本内容和样式"""
        txBody = elem.find('.//p:txBody', self.NS)
        if txBody is None:
            txBody = elem.find('.//a:txBody', self.NS)
        if txBody is None:
            # 检查 txXfrm (文本框)
            txXfrm = elem.find('.//p:txXfrm', self.NS)
            if txXfrm is not None:
                txBody = elem.find('.//a:txBody', self.NS)

        if txBody is None:
            return None, None

        text_parts = []
        text_style = {
            'font': 'Arial',
            'size': 18,
            'color': '#333333',
            'bold': False,
            'align': 'left'
        }

        for p in txBody.findall('.//a:p', self.NS):
            p_text = []
            for r in p.findall('.//a:r', self.NS):
                t = r.find('.//a:t', self.NS)
                if t is not None and t.text:
                    p_text.append(t.text)

                # 提取文本样式
                rPr = r.find('.//a:rPr', self.NS)
                if rPr is not None:
                    # 字体
                    latin = rPr.find('.//a:latin', self.NS)
                    if latin is not None:
                        text_style['font'] = latin.get('typeface', 'Arial')

                    # 字号
                    sz = rPr.get('sz')
                    if sz:
                        text_style['size'] = int(sz) // 100

                    # 粗体
                    text_style['bold'] = rPr.get('b', '0') == '1'

            if p_text:
                text_parts.append(' '.join(p_text))

            # 段落对齐
            pPr = p.find('.//a:pPr', self.NS)
            if pPr is not None:
                align = pPr.get('algn', 'l')
                align_map = {'l': 'left', 'r': 'right', 'ctr': 'center', 'just': 'justify'}
                text_style['align'] = align_map.get(align, 'left')

        # 从 bodyPr 提取默认样式
        bodyPr = txBody.find('.//a:bodyPr', self.NS)
        if bodyPr is not None:
            # 可以提取更多属性
            pass

        # 从 lstStyle 提取默认字体
        lstStyle = txBody.find('.//a:lstStyle', self.NS)
        if lstStyle is not None:
            defP = lstStyle.find('.//a:defPPr', self.NS)
            if defP is not None:
                defRPr = defP.find('.//a:defRPr', self.NS)
                if defRPr is not None:
                    latin = defRPr.find('.//a:latin', self.NS)
                    if latin is not None:
                        text_style['font'] = latin.get('typeface', text_style['font'])

        full_text = '\n'.join(text_parts) if text_parts else None

        return full_text, text_style if full_text else None

    def _print_slide_summary(self):
        """打印幻灯片解析摘要"""
        print(f"\n[SLIDE] 幻灯片解析完成:")
        type_counts = {}
        for slide in self.parsed_slides:
            t = slide.page_type
            type_counts[t] = type_counts.get(t, 0) + 1

        for page_type, count in type_counts.items():
            name, _ = self.PAGE_TYPE_MAP.get(page_type, (page_type, ''))
            print(f"   - {name}: {count} 张")

    def _extract_design_specs_from_slides(self) -> Dict[str, List[str]]:
        """
        从幻灯片中提取设计规范说明文本

        设计规范文本通常包含：
        - 字体规格说明（如"普惠体 Regular 55px"）
        - 布局说明（如"大标题为页面顶部左右居中 40px-80px"）
        - 字号规范（如"Bold80-150px"）
        """
        specs = {
            'cover': [],      # 封面页规范
            'toc': [],        # 目录页规范
            'chapter': [],    # 章节页规范
            'content': [],    # 内容页规范
            'ending': [],     # 结束页规范
        }

        # 规范文本特征关键词
        spec_patterns = [
            r'\d+px',           # 包含数字+px
            r'\d+pt',           # 包含数字+pt
            r'Bold|Regular|Light|Medium',  # 字重
            r'普惠体|Helvetica|Arial|微软雅黑',  # 字体名
            r'居中|左对齐|右对齐',  # 对齐方式
            r'标题|副标题|正文|正文内容',  # 元素类型
            r'字号|字体|字重',    # 字体属性
        ]

        for slide in self.parsed_slides:
            for shape in slide.shapes:
                if not shape.text_content:
                    continue

                # 跳过占位符
                if shape.is_placeholder:
                    continue

                text = shape.text_content.strip()

                # 检查是否为规范说明文本
                is_spec = False
                for pattern in spec_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        is_spec = True
                        break

                # 额外判断：通常规范文本较短且包含多个数字+单位组合
                if not is_spec and len(text) < 100:
                    # 检查是否包含多个数字+单位
                    units = re.findall(r'\d+\s*(px|pt|cm|mm)', text, re.IGNORECASE)
                    if len(units) >= 1:
                        is_spec = True

                if is_spec and text not in specs[slide.page_type]:
                    specs[slide.page_type].append(text)

        # 去重并排序
        for page_type in specs:
            specs[page_type] = list(dict.fromkeys(specs[page_type]))

        return specs

    def _detect_page_type(self, slide: ParsedSlide, slide_idx: int, total: int) -> str:
        """
        识别页面类型

        规则优先级：
        1. 幻灯片位置：第1张 → 封面，最后1张 → 结束页
        2. 文本关键词：
           - 包含"目录"、"TOC"、"Contents" → 目录页
           - 包含"章节"、"Chapter"、"SECTION" → 章节页
           - 包含"感谢"、"Thank"、"THE END"、"结束" → 结束页
        3. 形状特征：
           - 只有标题+副标题占位符 → 封面
           - 多个相似文本块（目录项） → 目录页
           - 纯色/渐变深色背景 → 章节/封面/结束
        4. 默认 → 内容页
        """
        # 1. 位置判断 - 最高优先级
        if slide_idx == 1:
            # 第一张可能是封面，但需要验证
            pass
        if slide_idx == total:
            return 'ending'

        # 2. 收集所有文本
        all_text = ' '.join([s.text_content for s in slide.shapes if s.text_content])
        all_text_lower = all_text.lower()

        # 3. 关键词检测
        # 目录页关键词
        toc_keywords = ['目录', 'toc', 'contents', '目录页', 'content', 'contents']
        for kw in toc_keywords:
            if kw.lower() in all_text_lower:
                return 'toc'

        # 结束页关键词
        ending_keywords = ['感谢', 'thank', 'the end', '结束', '谢谢', 'thanks', 'q&a', 'q & a']
        for kw in ending_keywords:
            if kw.lower() in all_text_lower:
                return 'ending'

        # 章节页关键词
        chapter_keywords = ['章节', 'chapter', 'section', 'part ']
        for kw in chapter_keywords:
            if kw.lower() in all_text_lower:
                return 'chapter'

        # 4. 数字编号模式（章节特征）
        # 匹配 "01", "02", "第1章", "PART 01" 等模式
        chapter_patterns = [
            r'\b0[1-9]\b',  # 01, 02, ...
            r'\b\d{2}\b',   # 两位数字
            r'第\s*\d+\s*章',  # 第1章
            r'part\s*\d+',   # PART 01
            r'chapter\s*\d+',  # Chapter 1
        ]
        for pattern in chapter_patterns:
            if re.search(pattern, all_text_lower):
                # 排除目录页（通常目录页也有数字编号）
                if not any(kw in all_text_lower for kw in ['目录', 'toc', 'contents']):
                    return 'chapter'

        # 5. 形状特征分析
        placeholder_types = [s.placeholder_type for s in slide.shapes if s.is_placeholder]
        has_title = 'title' in placeholder_types
        has_subtitle = 'subTitle' in placeholder_types
        has_body = 'body' in placeholder_types

        # 背景 darkness
        is_dark_bg = slide.background.is_dark if slide.background else False

        # 第一张 + 标题+副标题 → 封面
        if slide_idx == 1 and has_title:
            if has_subtitle or not has_body:
                return 'cover'

        # 深色背景 + 只有标题 → 章节页
        if is_dark_bg and has_title and not has_body:
            return 'chapter'

        # 检测目录特征：多个相似位置的文本块
        text_shapes = [s for s in slide.shapes if s.text_content and not s.is_placeholder]
        if len(text_shapes) >= 3:
            # 检查是否有多个垂直排列的相似尺寸文本块
            y_positions = [s.y for s in text_shapes]
            y_positions.sort()
            if len(y_positions) >= 3:
                # 检查间距是否均匀
                gaps = [y_positions[i+1] - y_positions[i] for i in range(len(y_positions)-1)]
                if gaps and max(gaps) - min(gaps) < 50:  # 间距差异小于50px
                    return 'toc'

        # 第一张默认封面
        if slide_idx == 1:
            return 'cover'

        # 默认为内容页
        return 'content'

    def _is_dark_color(self, hex_color: str) -> bool:
        """判断颜色是否为深色"""
        try:
            if not hex_color or hex_color.startswith('['):
                return False
            hex_color = hex_color.lstrip('#')
            if len(hex_color) < 6:
                return False
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            return brightness < 128
        except:
            return False

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """转换HEX颜色到RGB"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b)

    def _rgb_to_hex(self, r: int, g: int, b: int) -> str:
        """转换RGB到HEX颜色"""
        return f"#{r:02x}{g:02x}{b:02x}"

    def _resolve_scheme_color(self, scheme_ref: str, modifiers: Optional[Dict[str, int]] = None) -> str:
        """
        解析主题色引用到实际RGB颜色，应用亮度修正器

        Args:
            scheme_ref: 主题色引用，如 'accent1' 或 '[scheme:accent1]'
            modifiers: 亮度修正器，如 {'lumMod': 50000, 'lumOff': 0}

        Returns:
            实际的HEX颜色值
        """
        # 清理scheme引用格式
        if scheme_ref.startswith('[scheme:'):
            scheme_ref = scheme_ref[8:-1]

        # 获取基础颜色
        if scheme_ref not in self.theme_colors:
            return '#CCCCCC'  # 默认灰色

        color = self.theme_colors[scheme_ref]

        # 如果是嵌套的scheme引用，递归解析
        if color.is_scheme and color.value.startswith('[scheme:'):
            base_color = self._resolve_scheme_color(color.value)
        else:
            base_color = color.value

        # 如果没有修正器或基础色无效，直接返回
        if not modifiers or not base_color or base_color.startswith('['):
            return base_color if base_color and not base_color.startswith('[') else '#CCCCCC'

        try:
            # 转换到RGB
            r, g, b = self._hex_to_rgb(base_color)

            # 转换到HLS色彩空间
            h, l, s = colorsys.rgb_to_hls(r/255.0, g/255.0, b/255.0)

            # 应用亮度修正器
            # lumMod: 亮度乘数 (100000 = 100%, 50000 = 50%)
            # lumOff: 亮度偏移 (10000 = +10%, -10000 = -10%)
            if 'lumMod' in modifiers:
                l *= modifiers['lumMod'] / 100000.0
            if 'lumOff' in modifiers:
                l += modifiers['lumOff'] / 100000.0

            # 限制亮度范围 [0, 1]
            l = max(0.0, min(1.0, l))

            # 转换回RGB
            r, g, b = colorsys.hls_to_rgb(h, l, s)

            return self._rgb_to_hex(int(r*255), int(g*255), int(b*255))
        except Exception as e:
            print(f"[WARN]  颜色解析失败: {scheme_ref}, {e}")
            return base_color if base_color and not base_color.startswith('[') else '#CCCCCC'
    
    def _print_extraction_summary(self):
        """打印提取结果汇总"""
        print(f"\n[SIZE] 画布信息:")
        print(f"   尺寸: {self.canvas_info.width}x{self.canvas_info.height}")
        print(f"   比例: {self.canvas_info.aspect_ratio} ({self.canvas_info.format_name})")
        print(f"   viewBox: {self.canvas_info.viewBox}")
        
        print(f"\n[ART] 主题颜色:")
        for name, color in self.theme_colors.items():
            print(f"   {color.display_name}: {color.value}")
        
        print(f"\n[FONT] 字体方案:")
        font_names = {'majorFont': '标题字体', 'minorFont': '正文字体', 'bodyFont': 'Body字体'}
        for name, font in self.font_scheme.items():
            print(f"   {font_names.get(name, name)}: {font.typeface} ({font.size}px)")
        
        print(f"\n[PAGE] 页面布局类型:")
        for idx, layout in self.slide_layouts.items():
            ph_types = [ph.type for ph in layout.placeholders]
            print(f"   [{idx}] {layout.name}: {ph_types}")
    
    def _create_output_directory(self):
        """创建输出目录"""
        # 模板目录结构：直接在模板目录下放置 SVG 和 design_spec.md
        # images 子目录用于存放提取的媒体文件
        dirs = [self.output_dir, f"{self.output_dir}/images"]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
            print(f"[FOLDER] 创建目录: {d}")
    
    def _generate_complete_template(self):
        """生成完整模板"""
        self.extracted = ExtractedTemplate(
            canvas=self.canvas_info,
            colors=self.theme_colors,
            fonts=self.font_scheme,
            layouts=self.slide_layouts,
            backgrounds=self.background_styles
        )
        
        self._generate_design_spec()
        self._generate_all_page_templates()
    
    def _get_font_stack(self, font_type: str = 'minorFont') -> str:
        """获取字体栈（返回不带外层引号的字符串）"""
        font = self.font_scheme.get(font_type)
        primary = font.typeface if font else 'Microsoft YaHei'
        return f'{primary}, Microsoft YaHei, Arial, sans-serif'
    
    def _get_color(self, color_key: str, default: str = '#4285F4') -> str:
        """获取颜色，自动解析scheme引用"""
        if color_key in self.theme_colors:
            color = self.theme_colors[color_key]
            if not color.is_scheme:
                return color.value
            else:
                # 解析scheme引用
                resolved = self._resolve_scheme_color(color.value)
                return resolved if resolved and not resolved.startswith('[') else default
        return default
    
    def _analyze_layout_type(self, layout: SlideLayout) -> str:
        """分析布局类型"""
        ph_types = [ph.type for ph in layout.placeholders]
        
        if 'title' in ph_types and 'subTitle' in ph_types:
            return 'cover'
        elif 'title' in ph_types and 'body' in ph_types:
            if layout.is_dark_bg:
                return 'chapter'
            else:
                return 'content'
        elif 'title' in ph_types:
            if 'body' not in ph_types and layout.is_dark_bg:
                return 'chapter'
            return 'title'
        elif 'body' in ph_types:
            return 'content'
        else:
            return 'content'
    
    def _find_layout_for_type(self, page_type: str) -> Optional[SlideLayout]:
        """查找指定类型的布局"""
        for idx, layout in self.slide_layouts.items():
            detected_type = self._analyze_layout_type(layout)
            if detected_type == page_type:
                return layout
        return None
    
    def _generate_design_spec(self):
        """生成完整的 design_spec.md"""
        canvas = self.canvas_info
        title_font = self.font_scheme.get('majorFont', FontScheme('Microsoft YaHei', size=48))
        body_font = self.font_scheme.get('minorFont', FontScheme('Microsoft YaHei', size=18))

        # 提取设计规范文本
        design_specs = self._extract_design_specs_from_slides()

        master_placeholder_table = ""
        if self.slide_master and self.slide_master.placeholders:
            master_placeholder_table = "\n### 母版占位符\n\n| 名称 | 类型 | 位置 | 尺寸 |\n|------|------|------|------|\n"
            for ph in self.slide_master.placeholders:
                ph_name = self.PLACEHOLDER_MAP.get(ph.type, ph.type)
                master_placeholder_table += f"| {ph_name} | `{ph.type}` | ({ph.x}, {ph.y}) | {ph.cx}x{ph.cy} |\n"

        layout_summary = "\n### 版式布局详情\n\n| 版式名称 | 类型 | 占位符 | 背景 |\n|----------|------|--------|------|\n"
        for idx, layout in self.slide_layouts.items():
            ph_names = ', '.join([self.PLACEHOLDER_MAP.get(p.type, p.type) for p in layout.placeholders])
            bg = "深色" if layout.is_dark_bg else "浅色"
            layout_summary += f"| {layout.name} | {layout.type or '-'} | {ph_names} | {bg} |\n"

        # 生成设计规范说明章节
        spec_section = ""
        if any(design_specs.values()):
            spec_section = "\n---\n\n## 六、页面设计规范说明 [NEW] 从源文件提取\n\n"
            spec_section += "> 以下规范文本从源 PPTX 文件的幻灯片中自动提取，包含字体、字号、布局等设计要点。\n\n"

            page_type_names = {
                'cover': '封面页',
                'toc': '目录页',
                'chapter': '章节页',
                'content': '内容页',
                'ending': '结束页',
            }

            for page_type, specs in design_specs.items():
                if specs:
                    spec_section += f"### {page_type_names.get(page_type, page_type)}\n\n"
                    for spec in specs[:10]:  # 每种类型最多显示10条
                        spec_section += f"- {spec}\n"
                    spec_section += "\n"

        content = f'''# {self.template_name} - 设计规范

> 基于源文件 `{self.input_file.name}` 自动生成

---

## 一、模板概述

| 属性 | 描述 |
|------|------|
| **模板名称** | {self.template_name} |
| **源文件** | {self.input_file.name} |
| **幻灯片数** | {self.slide_count} |
| **适用场景** | 通用商业演示 |
| **设计调性** | 源文件风格解析 |

---

## 二、画布规范 [OK] 已解析

| 属性 | 值 |
|------|-----|
| **格式** | {canvas.aspect_ratio} ({canvas.format_name}) |
| **尺寸** | {canvas.width} × {canvas.height} px |
| **viewBox** | `{canvas.viewBox}` |
| **DPI** | 96 |

---

## 三、配色方案 [OK] 已解析

### 主题颜色完整列表

| 角色 | 色值 | 类型 |
|------|------|------|
'''

        for name, color in self.theme_colors.items():
            color_type = "方案色" if color.is_scheme else "RGB"
            content += f"| {color.display_name} | `{color.value}` | {color_type} |\n"

        bg_color = self._get_color('bg1', '#FFFFFF')
        text_color = self._get_color('dk1', '#333333')
        accent_color = self._get_color('accent1', '#4285F4')
        secondary_color = self._get_color('accent2', '#005587')

        content += f'''

### SVG 使用颜色

| 用途 | 色值 |
|------|------|
| 背景色 | `{bg_color}` |
| 文字色 | `{text_color}` |
| 强调色 | `{accent_color}` |
| 辅助色 | `{secondary_color}` |

---

## 四、排版体系 [OK] 已解析

### 字体方案

| 类型 | 字体名称 | 字号 | 字重 |
|------|----------|------|------|
| 标题 | {title_font.typeface} | {title_font.size}px | Bold |
| 正文 | {body_font.typeface} | {body_font.size}px | Regular |
| 页码 | Arial | 12px | Regular |

### 字体栈

```
"{title_font.typeface}", "Microsoft YaHei", Arial, sans-serif
```

{master_placeholder_table}

---

## 五、页面结构

### 通用布局结构

| 区域 | 位置 | 说明 |
|------|------|------|
| 内容区 | 居中 | 基于画布尺寸自动计算 |
| 页边距 | 60px | 默认安全边距 |
| 页脚 | 底部 | 包含页码和章节信息 |
{spec_section}
---

## 七、页面类型分析 [OK] 已解析

{self._generate_page_type_analysis()}

{layout_summary}

---

## 八、占位符规范

| 占位符 | 说明 |
|--------|------|
| `{{{{TITLE}}}}` | 主标题 |
| `{{{{SUBTITLE}}}}` | 副标题 |
| `{{{{AUTHOR}}}}` | 作者/机构 |
| `{{{{DATE}}}}` | 日期 |
| `{{{{PAGE_TITLE}}}}` | 页面标题 |
| `{{{{CHAPTER_NUM}}}}` | 章节编号 |
| `{{{{CHAPTER_TITLE}}}}` | 章节标题 |
| `{{{{CHAPTER_DESC}}}}` | 章节描述 |
| `{{{{SECTION_NAME}}}}` | 章节名称（页脚） |
| `{{{{PAGE_NUM}}}}` | 页码 |
| `{{{{CONTENT_AREA}}}}` | 内容区域 |
| `{{{{CONTACT_INFO}}}}` | 联系信息 |
| `{{{{TOC_ITEM_1-5}}}}` | 目录项 |
| `{{{{COPYRIGHT}}}}` | 版权信息 |

---

## 九、使用说明

1. 复制 `templates/` 目录到项目文件夹
2. 根据 `design_spec.md` 了解源文件风格
3. 使用占位符标记需要替换的内容
4. 通过 Executor 生成最终 SVG

---

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 源文件: {self.input_file.name}
> 解析: {len(self.theme_colors)} 颜色, {len(self.font_scheme)} 字体, {len(self.slide_layouts)} 布局
'''
        
        spec_path = Path(self.output_dir) / "design_spec.md"
        spec_path.write_text(content, encoding='utf-8')
        print(f"[FILE] 生成: {spec_path}")
    
    def _generate_page_type_analysis(self) -> str:
        """生成页面类型分析"""
        analysis = ""
        
        page_types = {
            'cover': ('封面页', '01_cover.svg', '封面'),
            'chapter': ('章节页', '02_chapter.svg', '章节'),
            'toc': ('目录页', '02_toc.svg', '目录'),
            'content': ('内容页', '03_content.svg', '内容'),
            'ending': ('结束页', '04_ending.svg', '结束'),
        }
        
        for page_type, (name, file, short) in page_types.items():
            layout = self._find_layout_for_type(page_type)
            if layout:
                analysis += f"### {name} (`{file}`)\n\n"
                analysis += f"- 版式来源: {layout.name}\n"
                analysis += f"- 占位符: {[self.PLACEHOLDER_MAP.get(p.type, p.type) for p in layout.placeholders]}\n"
                analysis += f"- 背景: {'深色' if layout.is_dark_bg else '浅色'}\n\n"
            else:
                analysis += f"### {name} (`{file}`)\n\n"
                analysis += f"- [WARN] 未找到对应版式，使用通用模板\n\n"
        
        return analysis
    
    def _generate_all_page_templates(self):
        """生成所有页面模板"""
        page_types = [
            ('cover', '01_cover.svg', '封面页'),
            ('toc', '02_toc.svg', '目录页'),
            ('chapter', '02_chapter.svg', '章节页'),
            ('content', '03_content.svg', '内容页'),
            ('ending', '04_ending.svg', '结束页'),
        ]
        
        for page_type, filename, desc in page_types:
            layout = self._find_layout_for_type(page_type)
            if layout:
                svg_content = self._generate_svg_from_layout(layout, page_type)
            else:
                print(f"[WARN]  未找到 {desc} 版式，使用通用模板")
                svg_content = self._generate_default_template(page_type)
            
            path = Path(self.output_dir) / filename
            path.write_text(svg_content, encoding='utf-8')
            print(f"[ART] 生成: {filename}")
    
    def _generate_svg_from_layout(self, layout: SlideLayout, page_type: str) -> str:
        """基于解析的布局生成SVG"""
        canvas = self.canvas_info
        bg_color = layout.background or self._get_color('bg1', '#FFFFFF')
        is_dark = layout.is_dark_bg
        
        title_font = self.font_scheme.get('majorFont', FontScheme('Microsoft YaHei', size=48))
        body_font = self.font_scheme.get('minorFont', FontScheme('Microsoft YaHei', size=18))
        
        title_color = "#FFFFFF" if is_dark else self._get_color('accent1', '#4285F4')
        text_color = "#FFFFFF" if is_dark else self._get_color('dk1', '#333333')
        
        header = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
'''
        
        if page_type == 'cover':
            return self._generate_cover_svg(canvas, title_font, body_font, bg_color, title_color, text_color, is_dark)
        elif page_type == 'chapter':
            return self._generate_chapter_svg(canvas, title_font, body_font, bg_color, title_color, text_color, is_dark)
        elif page_type == 'content':
            return self._generate_content_svg(canvas, title_font, body_font, bg_color, text_color)
        elif page_type == 'ending':
            return self._generate_ending_svg(canvas, title_font, body_font, bg_color, title_color, is_dark)
        elif page_type == 'toc':
            return self._generate_toc_svg(canvas, title_font, body_font, bg_color, text_color)
        else:
            return self._generate_default_template(page_type)
    
    def _generate_cover_svg(self, canvas: CanvasInfo, title_font: FontScheme, body_font: FontScheme, 
                             bg_color: str, title_color: str, text_color: str, is_dark: bool) -> str:
        """生成封面页SVG"""
        accent = self._get_color('accent1', '#4285F4')
        secondary = self._get_color('accent2', '#005587')
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
  <!-- 背景: 基于源文件 {bg_color} -->
  <defs>
    <linearGradient id="bg-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{accent}"/>
      <stop offset="100%" style="stop-color:{secondary}"/>
    </linearGradient>
  </defs>
  <rect width="{canvas.width}" height="{canvas.height}" fill="url(#bg-gradient)"/>
  
  <!-- 装饰圆 -->
  <circle cx="{canvas.width-180}" cy="150" r="200" fill="#FFFFFF" fill-opacity="0.1"/>
  <circle cx="{canvas.width-130}" cy="100" r="120" fill="#FFFFFF" fill-opacity="0.05"/>
  
  <!-- 左侧装饰线 -->
  <rect x="60" y="280" width="6" height="100" fill="#FFFFFF" rx="3"/>
  
  <!-- 主标题 (字体: {title_font.typeface}, 字号: {title_font.size}px) -->
  <text x="100" y="320" fill="{title_color}" font-family="{self._get_font_stack('majorFont')}" font-size="{title_font.size}" font-weight="bold">
    {{TITLE}}
  </text>
  
  <!-- 副标题 -->
  <text x="100" y="380" fill="#FFFFFF" fill-opacity="0.7" font-family="{self._get_font_stack('minorFont')}" font-size="24">
    {{SUBTITLE}}
  </text>
  
  <!-- 底部信息区 -->
  <rect x="0" y="{canvas.height-80}" width="{canvas.width}" height="80" fill="#000000" fill-opacity="0.2"/>
  <text x="100" y="{canvas.height-32}" fill="#FFFFFF" fill-opacity="0.8" font-family="Arial, sans-serif" font-size="16">
    {{DATE}}
  </text>
  <text x="{canvas.width-100}" y="{canvas.height-32}" text-anchor="end" fill="#FFFFFF" fill-opacity="0.8" font-family="Arial, sans-serif" font-size="16">
    {{AUTHOR}}
  </text>
</svg>
'''
    
    def _generate_chapter_svg(self, canvas: CanvasInfo, title_font: FontScheme, body_font: FontScheme,
                               bg_color: str, title_color: str, text_color: str, is_dark: bool) -> str:
        """生成章节页SVG"""
        accent = self._get_color('accent1', '#4285F4')
        secondary = self._get_color('accent2', '#005587')
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
  <!-- 背景渐变 -->
  <defs>
    <linearGradient id="bg-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{accent}"/>
      <stop offset="100%" style="stop-color:{secondary}"/>
    </linearGradient>
  </defs>
  <rect width="{canvas.width}" height="{canvas.height}" fill="url(#bg-gradient)"/>
  
  <!-- 大背景装饰圆 -->
  <circle cx="{canvas.width-80}" cy="{canvas.height-120}" r="400" fill="#FFFFFF" fill-opacity="0.05"/>
  
  <!-- 章节编号 -->
  <text x="{canvas.width//2}" y="180" text-anchor="middle" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="140" font-weight="bold" fill-opacity="0.15">
    {{CHAPTER_NUM}}
  </text>
  
  <!-- 章节标题 -->
  <rect x="80" y="300" width="8" height="60" fill="{bg_color}" rx="4"/>
  <text x="115" y="345" fill="{title_color}" font-family="{self._get_font_stack('majorFont')}" font-size="{title_font.size}" font-weight="bold">
    {{CHAPTER_TITLE}}
  </text>
  
  <!-- 章节描述 -->
  <text x="115" y="400" fill="#FFFFFF" fill-opacity="0.7" font-family="{self._get_font_stack('minorFont')}" font-size="20">
    {{CHAPTER_DESC}}
  </text>
</svg>
'''
    
    def _generate_content_svg(self, canvas: CanvasInfo, title_font: FontScheme, body_font: FontScheme,
                               bg_color: str, text_color: str) -> str:
        """生成内容页SVG"""
        accent = self._get_color('accent1', '#4285F4')
        
        header_height = 70
        footer_y = canvas.height - 60
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
  <!-- 背景: {bg_color} -->
  <rect width="{canvas.width}" height="{canvas.height}" fill="{bg_color}"/>
  
  <!-- 页眉区域 -->
  <rect x="0" y="0" width="{canvas.width}" height="{header_height}" fill="#FFFFFF"/>
  <line x1="0" y1="{header_height}" x2="{canvas.width}" y2="{header_height}" stroke="{accent}" stroke-width="3"/>
  
  <!-- 页面标题 (字体: {title_font.typeface}, 字号: 28px) -->
  <text x="60" y="45" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="28" font-weight="bold">
    {{PAGE_TITLE}}
  </text>
  
  <!-- 内容区域: AI灵活布局区 -->
  <rect x="40" y="{header_height+30}" width="{canvas.width-80}" height="{canvas.height-header_height-footer_y-60}" fill="#FFFFFF" rx="12"/>
  <rect x="40" y="{header_height+30}" width="{canvas.width-80}" height="{canvas.height-header_height-footer_y-60}" fill="none" stroke="#E2E8F0" stroke-width="2" rx="12" stroke-dasharray="8,4"/>
  
  <!-- 占位文字 -->
  <text x="{canvas.width//2}" y="{canvas.height//2}" text-anchor="middle" fill="#CBD5E1" font-family="{self._get_font_stack('minorFont')}" font-size="18">
    {{CONTENT_AREA}}
  </text>
  <text x="{canvas.width//2}" y="{canvas.height//2+35}" text-anchor="middle" fill="#E2E8F0" font-family="Arial, sans-serif" font-size="14">
    AI 灵活布局区 · {canvas.width-80}x{canvas.height-header_height-footer_y-60}
  </text>
  
  <!-- 页脚区域 -->
  <rect x="0" y="{footer_y}" width="{canvas.width}" height="60" fill="#FFFFFF"/>
  <line x1="0" y1="{footer_y}" x2="{canvas.width}" y2="{footer_y}" stroke="#E2E8F0" stroke-width="1"/>
  
  <!-- 章节标识 -->
  <rect x="40" y="{footer_y+18}" width="4" height="24" fill="{accent}" rx="2"/>
  <text x="56" y="{footer_y+36}" fill="#64748B" font-family="{self._get_font_stack('minorFont')}" font-size="12">
    {{SECTION_NAME}}
  </text>
  
  <!-- 页码 -->
  <text x="{canvas.width-60}" y="{footer_y+36}" text-anchor="end" fill="#94A3B8" font-family="Arial, sans-serif" font-size="14">
    {{PAGE_NUM}}
  </text>
</svg>
'''
    
    def _generate_ending_svg(self, canvas: CanvasInfo, title_font: FontScheme, body_font: FontScheme,
                              bg_color: str, title_color: str, is_dark: bool) -> str:
        """生成结束页SVG"""
        accent = self._get_color('accent1', '#4285F4')
        secondary = self._get_color('accent2', '#005587')
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
  <!-- 背景渐变 -->
  <defs>
    <linearGradient id="bg-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{accent}"/>
      <stop offset="100%" style="stop-color:{secondary}"/>
    </linearGradient>
  </defs>
  <rect width="{canvas.width}" height="{canvas.height}" fill="url(#bg-gradient)"/>
  
  <!-- 装饰圆 -->
  <circle cx="{canvas.width-80}" cy="{canvas.height-120}" r="350" fill="#FFFFFF" fill-opacity="0.05"/>
  
  <!-- 感谢语 -->
  <text x="{canvas.width//2}" y="260" text-anchor="middle" fill="{title_color}" font-family="{self._get_font_stack('majorFont')}" font-size="56" font-weight="bold">
    感谢聆听
  </text>
  
  <!-- 联系信息 -->
  <text x="{canvas.width//2}" y="360" text-anchor="middle" fill="#FFFFFF" fill-opacity="0.8" font-family="{self._get_font_stack('minorFont')}" font-size="20">
    {{CONTACT_INFO}}
  </text>
  
  <!-- 分隔线 -->
  <rect x="{canvas.width//2-100}" y="410" width="200" height="3" fill="#FFFFFF" fill-opacity="0.5" rx="1.5"/>
  
  <!-- 版权 -->
  <text x="{canvas.width//2}" y="{canvas.height-40}" text-anchor="middle" fill="#FFFFFF" fill-opacity="0.6" font-family="Arial, sans-serif" font-size="14">
    {{COPYRIGHT}}
  </text>
</svg>
'''
    
    def _generate_toc_svg(self, canvas: CanvasInfo, title_font: FontScheme, body_font: FontScheme,
                          bg_color: str, text_color: str) -> str:
        """生成目录页SVG"""
        accent = self._get_color('accent1', '#4285F4')
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
  <!-- 背景: {bg_color} -->
  <rect width="{canvas.width}" height="{canvas.height}" fill="{bg_color}"/>
  
  <!-- 页眉 -->
  <rect x="0" y="0" width="{canvas.width}" height="80" fill="#FFFFFF"/>
  <line x1="0" y1="80" x2="{canvas.width}" y2="80" stroke="{accent}" stroke-width="3"/>
  
  <!-- 标题 -->
  <text x="60" y="55" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="28" font-weight="bold">
    目录
  </text>
  
  <!-- 目录项区域 -->
  <rect x="40" y="120" width="{canvas.width-80}" height="{canvas.height-220}" fill="#FFFFFF" rx="12"/>
  
  <!-- 5个目录项 -->
  <g transform="translate(60, 150)">
    <rect x="0" y="0" width="{canvas.width-160}" height="80" fill="{bg_color}" rx="8"/>
    <circle cx="30" cy="40" r="20" fill="{accent}"/>
    <text x="30" y="46" text-anchor="middle" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="16" font-weight="bold">1</text>
    <text x="70" y="46" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="22" font-weight="bold">{{TOC_ITEM_1}}</text>
  </g>
  
  <g transform="translate(60, 250)">
    <rect x="0" y="0" width="{canvas.width-160}" height="80" fill="{bg_color}" rx="8"/>
    <circle cx="30" cy="40" r="20" fill="{accent}"/>
    <text x="30" y="46" text-anchor="middle" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="16" font-weight="bold">2</text>
    <text x="70" y="46" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="22" font-weight="bold">{{TOC_ITEM_2}}</text>
  </g>
  
  <g transform="translate(60, 350)">
    <rect x="0" y="0" width="{canvas.width-160}" height="80" fill="{bg_color}" rx="8"/>
    <circle cx="30" cy="40" r="20" fill="{accent}"/>
    <text x="30" y="46" text-anchor="middle" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="16" font-weight="bold">3</text>
    <text x="70" y="46" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="22" font-weight="bold">{{TOC_ITEM_3}}</text>
  </g>
  
  <g transform="translate(60, 450)">
    <rect x="0" y="0" width="{canvas.width-160}" height="80" fill="{bg_color}" rx="8"/>
    <circle cx="30" cy="40" r="20" fill="{accent}"/>
    <text x="30" y="46" text-anchor="middle" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="16" font-weight="bold">4</text>
    <text x="70" y="46" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="22" font-weight="bold">{{TOC_ITEM_4}}</text>
  </g>
  
  <g transform="translate(60, 550)">
    <rect x="0" y="0" width="{canvas.width-160}" height="80" fill="{bg_color}" rx="8"/>
    <circle cx="30" cy="40" r="20" fill="{accent}"/>
    <text x="30" y="46" text-anchor="middle" fill="#FFFFFF" font-family="Arial, sans-serif" font-size="16" font-weight="bold">5</text>
    <text x="70" y="46" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="22" font-weight="bold">{{TOC_ITEM_5}}</text>
  </g>
  
  <!-- 页脚 -->
  <rect x="0" y="{canvas.height-60}" width="{canvas.width}" height="60" fill="#FFFFFF"/>
  <line x1="0" y1="{canvas.height-60}" x2="{canvas.width}" y2="{canvas.height-60}" stroke="#E2E8F0" stroke-width="1"/>
  <text x="60" y="{canvas.height-26}" fill="#64748B" font-family="{self._get_font_stack('minorFont')}" font-size="12">{{SECTION_NAME}}</text>
  <text x="{canvas.width-60}" y="{canvas.height-26}" text-anchor="end" fill="#94A3B8" font-family="Arial, sans-serif" font-size="14">{{PAGE_NUM}}</text>
</svg>
'''
    
    def _generate_default_template(self, page_type: str) -> str:
        """生成默认模板"""
        canvas = self.canvas_info
        title_font = self.font_scheme.get('majorFont', FontScheme('Microsoft YaHei', size=48))
        body_font = self.font_scheme.get('minorFont', FontScheme('Microsoft YaHei', size=18))
        
        accent = self._get_color('accent1', '#4285F4')
        text_color = self._get_color('dk1', '#333333')
        
        placeholder_map = {
            'cover': ('主标题', '{{TITLE}}'),
            'chapter': ('章节标题', '{{CHAPTER_TITLE}}'),
            'content': ('页面标题', '{{PAGE_TITLE}}'),
            'ending': ('感谢聆听', '感谢聆听'),
            'toc': ('目录', '目录'),
        }
        
        name, placeholder = placeholder_map.get(page_type, ('内容', '{{CONTENT}}'))
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{canvas.viewBox}">
  <!-- 背景 -->
  <rect width="{canvas.width}" height="{canvas.height}" fill="#FFFFFF"/>
  
  <!-- 页眉 -->
  <rect x="0" y="0" width="{canvas.width}" height="60" fill="#FFFFFF"/>
  <line x1="0" y1="60" x2="{canvas.width}" y2="60" stroke="{accent}" stroke-width="2"/>
  
  <!-- 标题 -->
  <text x="60" y="40" fill="{text_color}" font-family="{self._get_font_stack('majorFont')}" font-size="24" font-weight="bold">
    {placeholder}
  </text>
  
  <!-- 内容区 -->
  <rect x="40" y="80" width="{canvas.width-80}" height="{canvas.height-160}" fill="none" stroke="#E2E8F0" stroke-width="1" rx="8" stroke-dasharray="4,4"/>
  
  <!-- 占位 -->
  <text x="{canvas.width//2}" y="{canvas.height//2}" text-anchor="middle" fill="#CBD5E1" font-family="{self._get_font_stack('minorFont')}" font-size="16">
    {{CONTENT_AREA}}
  </text>

  <!-- 页脚 -->
  <rect x="0" y="{canvas.height-60}" width="{canvas.width}" height="60" fill="#FFFFFF"/>
  <text x="60" y="{canvas.height-26}" fill="#64748B" font-family="Arial, sans-serif" font-size="12">{{SECTION_NAME}}</text>
  <text x="{canvas.width-60}" y="{canvas.height-26}" text-anchor="end" fill="#94A3B8" font-family="Arial, sans-serif" font-size="14">{{PAGE_NUM}}</text>
</svg>
'''

    # ==================== 幻灯片转换方法 ====================

    def _generate_slide_templates(self):
        """从解析的幻灯片生成模板文件"""
        if not self.parsed_slides:
            print("[WARN]  没有解析的幻灯片数据，使用布局生成模板")
            self._generate_all_page_templates()
            return

        print(f"\n[SLIDE] 从幻灯片生成模板...")

        # 按页面类型分组
        slide_groups = self._group_slides_by_type()

        # 为每种类型生成模板变体
        for page_type, slides in slide_groups.items():
            if not slides:
                continue

            # 聚类变体
            variants = self._cluster_slide_variants(slides)

            type_name, base_filename = self.PAGE_TYPE_MAP.get(page_type, (page_type, f"03_{page_type}.svg"))
            base_name = base_filename.replace('.svg', '')

            if len(variants) == 1:
                # 单一变体
                svg_content = self._generate_svg_from_slide(variants[0])
                filename = base_filename
                self._save_svg(filename, svg_content)
                print(f"[ART] 生成: {filename}")
            else:
                # 多个变体
                for i, slide in enumerate(variants):
                    suffix = chr(ord('a') + i)  # a, b, c...
                    filename = f"{base_name}_{suffix}.svg"
                    svg_content = self._generate_svg_from_slide(slide)
                    self._save_svg(filename, svg_content)
                    print(f"[ART] 生成: {filename} (来自幻灯片 {slide.index})")

    def _group_slides_by_type(self) -> Dict[str, List[ParsedSlide]]:
        """按页面类型分组幻灯片"""
        groups = {
            'cover': [],
            'toc': [],
            'chapter': [],
            'content': [],
            'ending': [],
        }
        for slide in self.parsed_slides:
            if slide.page_type in groups:
                groups[slide.page_type].append(slide)
        return groups

    def _cluster_slide_variants(self, slides: List[ParsedSlide]) -> List[ParsedSlide]:
        """根据设计相似度聚类幻灯片变体"""
        if len(slides) <= 1:
            return slides

        variants = []
        for slide in slides:
            fingerprint = self._get_design_fingerprint(slide)

            # 检查是否与现有变体相似
            is_new_variant = True
            for existing in variants:
                existing_fp = self._get_design_fingerprint(existing)
                if self._is_similar_design(fingerprint, existing_fp):
                    is_new_variant = False
                    break

            if is_new_variant:
                variants.append(slide)

        return variants

    def _get_design_fingerprint(self, slide: ParsedSlide) -> dict:
        """获取幻灯片的设计指纹"""
        shape_types = {}
        for s in slide.shapes:
            shape_types[s.shape_type] = shape_types.get(s.shape_type, 0) + 1

        bg_type = 'none'
        if slide.background:
            if slide.background.is_gradient:
                bg_type = 'gradient'
            else:
                bg_type = 'solid'

        # 计算文本块数量和占位符数量
        text_count = len([s for s in slide.shapes if s.text_content])
        placeholder_count = len([s for s in slide.shapes if s.is_placeholder])

        return {
            'shape_count': len(slide.shapes),
            'shape_types': shape_types,
            'image_count': len(slide.images),
            'bg_type': bg_type,
            'bg_is_dark': slide.background.is_dark if slide.background else False,
            'text_count': text_count,
            'placeholder_count': placeholder_count,
            'width': slide.shapes[0].width if slide.shapes else 0,
            'height': slide.shapes[0].height if slide.shapes else 0,
        }

    def _is_similar_design(self, fp1: dict, fp2: dict) -> bool:
        """判断两个设计指纹是否相似"""
        # 形状数量差异
        if abs(fp1['shape_count'] - fp2['shape_count']) > 3:
            return False

        # 图片数量差异
        if abs(fp1['image_count'] - fp2['image_count']) > 1:
            return False

        # 背景类型差异
        if fp1['bg_type'] != fp2['bg_type']:
            return False

        # 背景明暗差异
        if fp1['bg_is_dark'] != fp2['bg_is_dark']:
            return False

        # 占位符数量差异
        if abs(fp1['placeholder_count'] - fp2['placeholder_count']) > 1:
            return False

        return True

    def _generate_svg_from_slide(self, slide: ParsedSlide) -> str:
        """从解析的幻灯片生成SVG"""
        svg_parts = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{self.canvas_info.viewBox}">',
            f'  <!-- 从幻灯片 {slide.index} 生成，类型: {slide.page_type} -->',
            f'  <!-- 模板: {self.template_name} - {self.PAGE_TYPE_MAP.get(slide.page_type, (slide.page_type, ""))[0]} -->'
        ]

        # 背景
        if slide.background:
            svg_parts.append(self._svg_background(slide.background))
        else:
            # 默认背景
            svg_parts.append(f'  <rect width="{self.canvas_info.width}" height="{self.canvas_info.height}" fill="#FFFFFF"/>')

        # 母版装饰元素（背景图片和装饰形状）- 所有幻灯片共享
        for img in self.master_images:
            svg_parts.append(self._svg_image(img))
        for shape in self.master_shapes:
            if not shape.is_placeholder:
                # 跳过空文本形状
                if shape.text_content and not shape.text_content.strip():
                    continue
                svg_parts.append(self._svg_shape(shape))

        # 版式特定形状 - 根据幻灯片使用的layout_idx（先于图片）
        if slide.layout_idx in self.layout_shapes:
            for shape in self.layout_shapes[slide.layout_idx]:
                if not shape.is_placeholder:
                    svg_parts.append(self._svg_shape(shape))
                    # 如果形状有文本，也要添加
                    if shape.text_content and shape.text_content.strip():
                        svg_parts.append(self._svg_text_with_placeholder(shape, slide.page_type))

        # 版式特定图片 - 根据幻灯片使用的layout_idx
        if slide.layout_idx in self.layout_images:
            for img in self.layout_images[slide.layout_idx]:
                svg_parts.append(self._svg_image(img))

        # 排序形状（按z_index）
        sorted_shapes = sorted(slide.shapes, key=lambda s: s.z_index)

        # 设计元素（非占位符形状）- 不包含文本
        for shape in sorted_shapes:
            if not shape.is_placeholder:
                # 椭圆、矩形等装饰元素
                if shape.shape_type in ['rect', 'ellipse', 'line', 'path']:
                    svg_parts.append(self._svg_shape(shape))

        # 文本/内容区域 - 根据页面类型智能生成占位符
        text_shapes = [s for s in sorted_shapes if (s.text_content and s.text_content.strip()) or s.is_placeholder]
        for shape in text_shapes:
            svg_parts.append(self._svg_text_with_placeholder(shape, slide.page_type))

        # 幻灯片特定图片
        for img in slide.images:
            svg_parts.append(self._svg_image(img))

        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)

    def _svg_text_with_placeholder(self, shape: ParsedShape, page_type: str) -> str:
        """根据形状和页面类型生成带占位符的文本"""
        # 跳过空文本
        if not shape.text_content or not shape.text_content.strip():
            return ""

        # 确定占位符类型
        placeholder = self._determine_placeholder(shape, page_type)

        style = shape.text_style or {}
        font_family = style.get('font', 'Arial')
        font_size = style.get('size', 18)
        font_weight = "bold" if style.get('bold', False) else "normal"

        # 文本颜色
        if style.get('color'):
            fill = style['color']
        else:
            fill = '#333333'

        # 计算位置
        text_x = shape.x
        text_y = shape.y + shape.height / 2 + font_size / 3
        anchor = "start"

        if style.get('align') == 'center':
            text_x = shape.x + shape.width / 2
            anchor = "middle"

        return f'  <text x="{text_x}" y="{text_y}" text-anchor="{anchor}" fill="{fill}" font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}">{placeholder}</text>'

    def _determine_placeholder(self, shape: ParsedShape, page_type: str) -> str:
        """根据形状特征和页面类型确定占位符"""
        # 如果是占位符类型，使用预设映射
        if shape.is_placeholder and shape.placeholder_type:
            return self.PLACEHOLDER_TYPE_MAP.get(shape.placeholder_type, '{{CONTENT}}')

        # 根据文本内容和位置智能判断
        text = (shape.text_content or '').lower()

        # 根据页面类型判断
        if page_type == 'cover':
            if '部门' in text or 'department' in text:
                return '{{DEPARTMENT}}'
            if '副标题' in text:
                return '{{SUBTITLE}}'
            if '主标题' in text or 'title' in text:
                return '{{TITLE}}'
            if '演讲人' in text or 'speaker' in text or 'author' in text:
                return '{{AUTHOR}}'
            if '日期' in text or 'date' in text or re.match(r'\d{4}\.\d+', text):
                return '{{DATE}}'
            # 按位置判断
            if shape.y < 150:  # 顶部区域
                return '{{TITLE}}'
            return '{{SUBTITLE}}'

        elif page_type == 'toc':
            if '目录' in text or 'toc' in text or 'content' in text:
                return '{{TOC_TITLE}}'
            return '{{TOC_ITEM}}'

        elif page_type == 'chapter':
            if re.match(r'0?\d', text) or '章节' in text:
                return '{{CHAPTER_NUM}}'
            return '{{CHAPTER_TITLE}}'

        elif page_type == 'content':
            # 按位置和尺寸判断
            if shape.y < 180 and shape.height < 100:  # 顶部标题区
                return '{{PAGE_TITLE}}'
            if '副标题' in text:
                return '{{SUBTITLE}}'
            if '标题' in text and shape.y < 400:
                return '{{ITEM_TITLE}}'
            if '说明' in text or '正文' in text or '内容' in text:
                return '{{CONTENT}}'
            # 默认内容
            if shape.height > 200:
                return '{{CONTENT}}'
            return '{{ITEM_TITLE}}'

        elif page_type == 'ending':
            if '感谢' in text or 'thank' in text:
                return '{{THANK_YOU}}'
            if '联系' in text or 'contact' in text:
                return '{{CONTACT_INFO}}'
            return '{{THANK_YOU}}'

        # 默认
        return '{{CONTENT}}'

    def _svg_background(self, bg: BackgroundStyle) -> str:
        """生成背景SVG元素"""
        if bg.is_gradient and bg.gradient_colors:
            # 渐变背景
            stops = []
            for i, color in enumerate(bg.gradient_colors):
                offset = int(100 * i / (len(bg.gradient_colors) - 1)) if len(bg.gradient_colors) > 1 else 0
                stops.append(f'      <stop offset="{offset}%" style="stop-color:{color}"/>')

            return f'''  <defs>
    <linearGradient id="bg-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
{chr(10).join(stops)}
    </linearGradient>
  </defs>
  <rect width="{self.canvas_info.width}" height="{self.canvas_info.height}" fill="url(#bg-gradient)"/>'''
        else:
            # 纯色背景
            return f'  <rect width="{self.canvas_info.width}" height="{self.canvas_info.height}" fill="{bg.color}"/>'

    def _svg_shape(self, shape: ParsedShape) -> str:
        """生成形状SVG元素"""
        elements = []

        if shape.shape_type == 'rect':
            # 矩形
            style = []
            if shape.fill_color:
                style.append(f"fill:{shape.fill_color}")
                if shape.fill_opacity < 1.0:
                    style.append(f"fill-opacity:{shape.fill_opacity}")
            else:
                style.append("fill:none")

            if shape.stroke_color and shape.stroke_width > 0:
                style.append(f"stroke:{shape.stroke_color}")
                style.append(f"stroke-width:{shape.stroke_width}")

            style_attr = f" style=\"{';'.join(style)}\"" if style else ""

            # 检查是否有旋转
            transform = ""
            if shape.rotation:
                cx = shape.x + shape.width / 2
                cy = shape.y + shape.height / 2
                transform = f' transform="rotate({shape.rotation} {cx} {cy})"'

            elements.append(f'  <rect x="{shape.x}" y="{shape.y}" width="{shape.width}" height="{shape.height}"{style_attr}{transform}/>')

            # 如果有文本，添加文本元素
            if shape.text_content and not shape.is_placeholder:
                elements.append(self._svg_text(shape))

        elif shape.shape_type == 'ellipse':
            # 椭圆
            cx = shape.x + shape.width / 2
            cy = shape.y + shape.height / 2
            rx = shape.width / 2
            ry = shape.height / 2

            style = []
            if shape.fill_color:
                style.append(f"fill:{shape.fill_color}")
            else:
                style.append("fill:none")

            if shape.stroke_color and shape.stroke_width > 0:
                style.append(f"stroke:{shape.stroke_color}")
                style.append(f"stroke-width:{shape.stroke_width}")

            style_attr = f" style=\"{';'.join(style)}\"" if style else ""
            elements.append(f'  <ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"{style_attr}/>')

            if shape.text_content:
                elements.append(self._svg_text(shape))

        elif shape.shape_type == 'line':
            # 线条
            style = []
            if shape.stroke_color:
                style.append(f"stroke:{shape.stroke_color}")
                style.append(f"stroke-width:{max(shape.stroke_width, 1)}")
            else:
                style.append("stroke:#000000")
                style.append("stroke-width:1")

            style_attr = f" style=\"{';'.join(style)}\""
            elements.append(f'  <line x1="{shape.x}" y1="{shape.y}" x2="{shape.x + shape.width}" y2="{shape.y + shape.height}"{style_attr}/>')

        elif shape.shape_type == 'text':
            # 纯文本
            elements.append(self._svg_text(shape))

        elif shape.shape_type == 'path' and shape.path_data:
            # 自定义路径
            style = []
            if shape.fill_color:
                style.append(f"fill:{shape.fill_color}")
            else:
                style.append("fill:none")

            if shape.stroke_color:
                style.append(f"stroke:{shape.stroke_color}")
                style.append(f"stroke-width:{shape.stroke_width}")

            style_attr = f" style=\"{';'.join(style)}\"" if style else ""
            elements.append(f'  <path d="{shape.path_data}"{style_attr}/>')

        else:
            # 默认为矩形
            style = []
            if shape.fill_color:
                style.append(f"fill:{shape.fill_color}")
            else:
                style.append("fill:none")

            style_attr = f" style=\"{';'.join(style)}\"" if style else ""
            elements.append(f'  <rect x="{shape.x}" y="{shape.y}" width="{shape.width}" height="{shape.height}"{style_attr}/>')

        return '\n'.join(elements)

    def _svg_text(self, shape: ParsedShape) -> str:
        """生成文本SVG元素"""
        style = shape.text_style or {}
        font_family = style.get('font', 'Arial')
        font_size = style.get('size', 18)
        font_weight = "bold" if style.get('bold', False) else "normal"
        text_align = style.get('align', 'left')

        # 文本颜色
        if style.get('color'):
            fill = style['color']
        elif shape.fill_color:
            fill = shape.fill_color
        else:
            fill = '#333333'

        # 计算文本位置
        text_x = shape.x
        anchor = "start"

        if text_align == 'center':
            text_x = shape.x + shape.width / 2
            anchor = "middle"
        elif text_align == 'right':
            text_x = shape.x + shape.width
            anchor = "end"

        # 垂直居中
        text_y = shape.y + shape.height / 2 + font_size / 3

        # 处理多行文本
        text_content = shape.text_content or ""
        lines = text_content.split('\n')

        if len(lines) > 1:
            # 多行文本
            text_elements = []
            line_height = font_size * 1.4
            start_y = shape.y + shape.height / 2 - (len(lines) - 1) * line_height / 2 + font_size / 3

            for i, line in enumerate(lines):
                y = start_y + i * line_height
                text_elements.append(f'  <text x="{text_x}" y="{y}" text-anchor="{anchor}" fill="{fill}" font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}">{self._escape_xml(line)}</text>')

            return '\n'.join(text_elements)
        else:
            return f'  <text x="{text_x}" y="{text_y}" text-anchor="{anchor}" fill="{fill}" font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}">{self._escape_xml(text_content)}</text>'

    def _svg_placeholder(self, shape: ParsedShape) -> str:
        """将占位符形状转换为模板占位符"""
        ph_type = shape.placeholder_type or 'body'
        placeholder_text = self.PLACEHOLDER_TYPE_MAP.get(ph_type, '{{CONTENT}}')

        style = shape.text_style or {}
        font_family = style.get('font', self._get_font_stack('majorFont'))
        font_size = style.get('size', 24)
        font_weight = "bold" if style.get('bold', False) else "normal"

        # 文本颜色
        if style.get('color'):
            fill = style['color']
        else:
            # 根据背景选择颜色
            if self.parsed_slides:
                first_slide = self.parsed_slides[0]
                if first_slide.background and first_slide.background.is_dark:
                    fill = "#FFFFFF"
                else:
                    fill = "#333333"
            else:
                fill = "#333333"

        # 计算位置
        text_x = shape.x
        text_y = shape.y + shape.height / 2 + font_size / 3
        anchor = "start"

        if style.get('align') == 'center':
            text_x = shape.x + shape.width / 2
            anchor = "middle"

        return f'  <text x="{text_x}" y="{text_y}" text-anchor="{anchor}" fill="{fill}" font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}">{placeholder_text}</text>'

    def _svg_image(self, img: ParsedImage) -> str:
        """生成图片SVG元素"""
        if not img.image_path:
            return f'  <!-- 图片 {img.name} 缺少路径 -->'

        return f'  <image x="{img.x}" y="{img.y}" width="{img.width}" height="{img.height}" xlink:href="{img.image_path}"/>'

    def _escape_xml(self, text: str) -> str:
        """转义XML特殊字符"""
        if not text:
            return ""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))

    def _save_svg(self, filename: str, content: str):
        """保存SVG文件"""
        path = Path(self.output_dir) / filename
        path.write_text(content, encoding='utf-8')

    def _extract_media(self, zf: zipfile.ZipFile):
        """提取媒体文件"""
        try:
            media_files = [f for f in zf.namelist() if f.startswith('ppt/media/')]
            
            if media_files:
                count = 0
                for f in media_files:
                    filename = Path(f).name
                    filepath = Path(self.output_dir) / "images" / filename
                    
                    with zf.open(f) as src, open(filepath, 'wb') as dst:
                        dst.write(src.read())
                    count += 1
                
                print(f"[IMG]  提取媒体文件 {count} 个到 images/ 目录")
        except Exception as e:
            print(f"[WARN]  媒体提取跳过: {e}")


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description='PPTX/POTX to Layout Template Converter (增强版)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
功能说明:
    完整解析 PPTX/POTX 文件，提取所有要素：

    [OK] 画布: 尺寸、比例、viewBox
    [OK] 配色: 完整主题颜色 (srgbClr, schemeClr)
    [OK] 排版: 字体方案 (majorFont, minorFont)
    [OK] 页面结构: 占位符位置、尺寸

    [NEW] 幻灯片解析: 直接解析每张幻灯片内容
    [NEW] 页面类型识别: 自动识别封面、目录、章节、内容、结束页
    [NEW] 多变体输出: 同类页面不同设计会生成多个变体
    [NEW] 设计保留: 保留原始PPT的形状、文本位置和样式

    默认输出到 templates/layouts/{文件名}/ 目录：
    - design_spec.md      (完整设计规范)
    - 01_cover.svg        (封面页)
    - 02_toc.svg          (目录页)
    - 02_chapter.svg      (章节页)
    - 03_content.svg      (内容页 - 基于布局)
    - 03_content_a/b/c... (内容页变体 - 基于实际幻灯片)
    - 04_ending.svg       (结束页)
    - images/             (媒体文件)

示例:
    python pptx_to_template.py my_presentation.pptx
    python pptx_to_template.py template.potx -o templates/layouts/my_template
        '''
    )

    parser.add_argument('input_file', help='输入的 PPTX 或 POTX 文件路径')
    parser.add_argument('-o', '--output', dest='output_dir', default=None,
                        help='输出目录路径 (默认: templates/layouts/{文件名}/)')

    args = parser.parse_args()

    converter = PPTXToTemplateConverter(args.input_file, args.output_dir)
    success = converter.convert()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
