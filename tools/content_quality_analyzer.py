#!/usr/bin/env python3
"""
Content Quality Analyzer for PPT Master
======================================

This tool analyzes generated SVG content for quality assurance,
checking for completeness, consistency, and adherence to design guidelines.
It helps users improve their generated presentations before final export.
"""

import os
import re
import argparse
from pathlib import Path
from typing import List, Dict, Any
import xml.etree.ElementTree as ET

def analyze_svg_content(svg_path: Path) -> Dict[str, Any]:
    """
    Analyze a single SVG file for quality indicators
    
    Args:
        svg_path: Path to the SVG file
        
    Returns:
        Dictionary containing analysis results
    """
    try:
        # Parse the SVG file
        tree = ET.parse(svg_path)
        root = tree.getroot()
        
        # Get SVG dimensions
        width = root.get('width', '0')
        height = root.get('height', '0')
        
        # Check for important elements
        text_elements = root.findall('.//{http://www.w3.org/2000/svg}text')
        rect_elements = root.findall('.//{http://www.w3.org/2000/svg}rect')
        path_elements = root.findall('.//{http://www.w3.org/2000/svg}path')
        image_elements = root.findall('.//{http://www.w3.org/2000/svg}image')
        
        # Check for title element (recommended)
        title_elements = root.findall('.//{http://www.w3.org/2000/svg}title')
        
        # Count unique colors (basic color diversity check)
        colors = set()
        for element in root.iter():
            if 'fill' in element.attrib:
                colors.add(element.attrib['fill'])
            if 'stroke' in element.attrib:
                colors.add(element.attrib['stroke'])
                
        # Basic composition analysis
        has_title = len(title_elements) > 0
        has_text_content = len(text_elements) > 0
        has_visual_elements = len(rect_elements) + len(path_elements) + len(image_elements) > 0
        
        # Content length analysis (if there are text elements)
        total_text_length = 0
        for text in text_elements:
            text_content = text.text or ''
            total_text_length += len(text_content.strip())
            
        return {
            'file': str(svg_path),
            'width': width,
            'height': height,
            'has_title': has_title,
            'text_count': len(text_elements),
            'text_length': total_text_length,
            'visual_elements_count': len(rect_elements) + len(path_elements) + len(image_elements),
            'color_count': len(colors),
            'has_text_content': has_text_content,
            'has_visual_elements': has_visual_elements,
            'is_empty': not (has_text_content or has_visual_elements)
        }
    except ET.ParseError as e:
        return {'file': str(svg_path), 'error': f'XML Parse Error: {str(e)}'}
    except Exception as e:
        return {'file': str(svg_path), 'error': f'Error: {str(e)}'}

def analyze_project_folder(project_path: Path) -> Dict[str, Any]:
    """
    Analyze all SVG files in a project folder
    
    Args:
        project_path: Path to the project directory
        
    Returns:
        Dictionary with overall analysis results  
    """
    svg_output_dir = project_path / 'svg_output'
    if not svg_output_dir.exists():
        return {'error': 'svg_output directory not found in project'}
    
    # Find all SVG files
    svg_files = list(svg_output_dir.glob('*.svg'))
    if not svg_files:
        return {'error': 'No SVG files found in svg_output directory'}
    
    analysis_results = []
    for svg_file in svg_files:
        analysis = analyze_svg_content(svg_file)
        analysis_results.append(analysis)
    
    # Overall statistics
    total_files = len(svg_files)
    files_with_errors = len([r for r in analysis_results if 'error' in r])
    files_with_text = len([r for r in analysis_results if r.get('has_text_content', False)])
    files_with_visual = len([r for r in analysis_results if r.get('has_visual_elements', False)])
    empty_files = len([r for r in analysis_results if r.get('is_empty', False)])
    
    return {
        'project': str(project_path),
        'total_files': total_files,
        'files_with_errors': files_with_errors,
        'files_with_text_content': files_with_text,
        'files_with_visual_elements': files_with_visual,
        'empty_files': empty_files,
        'per_file_analysis': analysis_results
    }

def print_analysis_summary(analysis: Dict[str, Any]) -> None:
    """
    Print a human-readable summary of the analysis
    """
    print("Content Quality Analysis Report")
    print("=" * 40)
    
    if 'error' in analysis:
        print(f"Error: {analysis['error']}")
        return
        
    print(f"Project: {analysis['project']}")
    print(f"Total SVG Files: {analysis['total_files']}")
    print(f"Files with Errors: {analysis['files_with_errors']}")
    print(f"Files with Text Content: {analysis['files_with_text_content']}")
    print(f"Files with Visual Elements: {analysis['files_with_visual_elements']}")
    print(f"Empty Files (No Content): {analysis['empty_files']}")
    
    # Check for issues
    issues = []
    if analysis['files_with_errors'] > 0:
        issues.append(f"{analysis['files_with_errors']} files have parsing errors")
    if analysis['empty_files'] > 0:
        issues.append(f"{analysis['empty_files']} files are empty")
    if analysis['files_with_text_content'] == 0:
        issues.append("No files contain text content")
    if analysis['files_with_visual_elements'] == 0:
        issues.append("No files contain visual elements")
        
    if issues:
        print("\nIssues Found:")
        for issue in issues:
            print(f"  - {issue}")
        
    # Per file analysis
    print("\nDetailed Analysis per File:")
    for result in analysis['per_file_analysis']:
        print(f"\nFile: {os.path.basename(result['file'])}")
        if 'error' in result:
            print(f"  Error: {result['error']}")
            continue
            
        print(f"  Dimensions: {result['width']} x {result['height']}")
        print(f"  Has Title: {result['has_title']}")
        print(f"  Text Elements: {result['text_count']}")
        print(f"  Visual Elements: {result['visual_elements_count']}")
        print(f"  Unique Colors: {result['color_count']}")
        print(f"  Content Status: {'Complete' if result['has_text_content'] or result['has_visual_elements'] else 'Incomplete'}")

def main():
    """
    Main function for command-line usage
    """
    parser = argparse.ArgumentParser(
        description='Analyze generated SVG content quality',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s projects/my_project
  %(prog)s --format json projects/my_project
        """
    )
    parser.add_argument('project_path', help='Path to the project directory to analyze')
    parser.add_argument('--format', '-f', choices=['text', 'json'], 
                       default='text', help='Output format (default: text)')
    parser.add_argument('--verbose', '-v', action='store_true', 
                       help='Enable verbose output')
    
    args = parser.parse_args()
    
    project_path = Path(args.project_path)
    if not project_path.exists():
        print(f"Error: Project directory '{project_path}' does not exist")
        return 1
    
    # Perform analysis
    analysis = analyze_project_folder(project_path)
    
    if args.format == 'json':
        import json
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
    else:
        print_analysis_summary(analysis)
    
    return 0

if __name__ == '__main__':
    exit(main())