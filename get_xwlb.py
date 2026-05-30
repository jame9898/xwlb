import requests
from datetime import datetime, timedelta
import re
import html as html_module
import sys
import os
import time
import random
import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

REQUEST_DELAY_MIN = 0.3
REQUEST_DELAY_MAX = 0.8
DAY_DELAY_MIN = 1.5
DAY_DELAY_MAX = 3.0
MAX_WORKERS = 5

def random_delay(min_sec, max_sec):
    time.sleep(random.uniform(min_sec, max_sec))

def fetch_html(url, timeout=15, retries=2):
    for attempt in range(retries):
        try:
            random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            response = session.get(url, timeout=timeout)
            response.encoding = 'utf-8'
            return response.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 + random.random())
            else:
                return None
    return None

def fetch_detail_content(url):
    html_content = fetch_html(url)
    if not html_content:
        return None
    
    start_match = re.search(r'<div class="content_area"[^>]*>', html_content)
    if not start_match:
        return None
    
    start_pos = start_match.end()
    end_match = re.search(r'<div class="zebian">', html_content[start_pos:])
    
    if end_match:
        content = html_content[start_pos:start_pos + end_match.start()]
    else:
        content = html_content[start_pos:start_pos + 8000]
    
    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
    content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
    content = re.sub(r'<br\s*/?>', '\n', content)
    content = re.sub(r'</p>', '\n', content)
    content = re.sub(r'<[^>]+>', '', content)
    content = html_module.unescape(content)
    content = re.sub(r'&nbsp;', ' ', content)
    content = re.sub(r'&[ld]dquo;', '"', content)
    content = re.sub(r'&mdash;', '——', content)
    content = re.sub(r'&middot;', '·', content)
    content = re.sub(r'\n\s*\n+', '\n', content)
    content = re.sub(r'[ \t]+', ' ', content)
    
    return content.strip() if content.strip() else None

def fetch_all_details_concurrent(news_items, max_workers=MAX_WORKERS):
    results = {}
    total = len(news_items)
    completed = [0]
    failed = [0]
    
    def fetch_one(item):
        content = fetch_detail_content(item['url'])
        if not content:
            time.sleep(1)
            content = fetch_detail_content(item['url'])
        return item['url'], content
    
    print(f"    共 {total} 条新闻待获取...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, item): item for item in news_items}
        for future in as_completed(futures):
            url, content = future.result()
            results[url] = content
            completed[0] += 1
            if content is None:
                failed[0] += 1
                print(f"    [{completed[0]}/{total}] 获取失败: {futures[future]['title'][:20]}...")
            else:
                print(f"    [{completed[0]}/{total}] 已获取: {futures[future]['title'][:20]}...")
    
    for item in news_items:
        item['content'] = results.get(item['url'])
    
    return failed[0]

def is_brief_news(title):
    return '快讯' in title

def format_content(text, title="", is_md=True):
    if not text:
        return ""
    
    is_brief = is_brief_news(title)
    paragraphs = text.split('\n')
    formatted = []
    brief_items = []
    current_title = None
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        
        if is_brief:
            if p.startswith('央视网消息（新闻联播）'):
                p = re.sub(r'^央视网消息（新闻联播）[：:]\s*', '', p)
            if not p:
                continue
            
            if not re.search(r'[。！？]$', p):
                current_title = p
            else:
                if current_title:
                    if is_md:
                        brief_items.append('***' + current_title + '***\n　　' + p)
                    else:
                        brief_items.append('【' + current_title + '】\n　　' + p)
                    current_title = None
                else:
                    formatted.append('　　' + p)
        else:
            formatted.append('　　' + p)
    
    if is_brief:
        return '\n\n'.join(brief_items)
    
    return '\n'.join(formatted)

def clean_title(title):
    title = title.strip()
    title = re.sub(r'^\[视频\]\s*', '', title)
    return title.strip()

def parse_day_page(html):
    if not html:
        return []
    
    pattern = r'<a href="(https://tv\.cctv\.com/\d{4}/\d{2}/\d{2}/VIDE[^"]+)"[^>]*title="([^"]+)"'
    matches = re.findall(pattern, html)
    
    seen = set()
    items = []
    for url, title in matches:
        title = clean_title(title)
        if title and len(title) > 3 and '完整版' not in title and not title.startswith('《新闻联播》'):
            key = title[:20]
            if key not in seen:
                seen.add(key)
                items.append({'title': title, 'url': url})
    
    return items

CHINESE_NUMS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
                '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
                '二十一', '二十二', '二十三', '二十四', '二十五', '二十六', '二十七', '二十八', '二十九', '三十']

def to_chinese(num):
    return CHINESE_NUMS[num] if 0 < num < len(CHINESE_NUMS) else str(num)

def format_summary(date_str, news_items):
    lines = ["=" * 50, f"{date_str} 新闻联播简介如下：", "=" * 50]
    for i, item in enumerate(news_items, 1):
        lines.append(f"第{to_chinese(i)}条，{item['title']}")
    lines.extend(["=" * 50, f"（来源：{date_str}的新闻联播 - 央视网新闻联播主页 - https://tv.cctv.com/lm/xwlb/index.shtml）", "=" * 50])
    return '\n'.join(lines)

def format_md_summary(date_str, news_items):
    lines = [f"# {date_str} 新闻联播", "", "> 来源：央视网新闻联播主页 - https://tv.cctv.com/lm/xwlb/index.shtml", ""]
    for i, item in enumerate(news_items, 1):
        lines.append(f"第{to_chinese(i)}条：{item['title']}")
        lines.append("")
    return '\n'.join(lines)

def format_md_detail(date_str, news_items):
    lines = [f"# {date_str} 新闻联播", "", "> 来源：央视网新闻联播主页 - https://tv.cctv.com/lm/xwlb/index.shtml", ""]
    for i, item in enumerate(news_items, 1):
        lines.append(f"## 第{to_chinese(i)}条：{item['title']}")
        lines.append("")
        if item.get('content'):
            lines.append(format_content(item['content'], item['title'], is_md=True))
        else:
            lines.append("暂无详细内容")
        lines.append("")
    return '\n'.join(lines)

def format_txt_detail(date_str, news_items):
    lines = []
    for i, item in enumerate(news_items, 1):
        if item.get('content'):
            lines.append("=" * 50)
            lines.append(f"第{to_chinese(i)}条：{item['title']}")
            lines.append("=" * 50)
            lines.append("")
            lines.append(format_content(item['content'], item['title'], is_md=False))
            lines.append("")
    return '\n'.join(lines)

def get_output_dirs(year, month):
    base_dir = os.path.join("News", str(year), f"{month:02d}")
    summary_dir = os.path.join(base_dir, "summary")
    detail_dir = os.path.join(base_dir, "detail")
    os.makedirs(summary_dir, exist_ok=True)
    os.makedirs(detail_dir, exist_ok=True)
    return summary_dir, detail_dir

def fetch_single_day(year, month, day, use_md=False, fetch_detail=False):
    date_str = f"{year}年{month:02d}月{day:02d}日"
    target_str = f"{year}{month:02d}{day:02d}"
    
    url = f"https://tv.cctv.com/lm/xwlb/day/{target_str}.shtml"
    html = fetch_html(url)
    
    if not html:
        return None, f"未找到 {date_str} 的新闻内容"
    
    news_items = parse_day_page(html)
    if not news_items:
        return None, f"未找到 {date_str} 的新闻内容"
    
    summary_dir, detail_dir = get_output_dirs(year, month)
    ext = ".md" if use_md else ".txt"
    
    summary_file = os.path.join(summary_dir, f"{target_str}_summary{ext}")
    
    if use_md:
        summary = format_md_summary(date_str, news_items)
    else:
        summary = format_summary(date_str, news_items)
    
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(summary)
    
    result = {
        'date_str': date_str,
        'news_count': len(news_items),
        'summary_file': summary_file,
        'detail_file': None,
        'success_count': 0,
        'failed_count': 0
    }
    
    if fetch_detail:
        failed_count = fetch_all_details_concurrent(news_items)
        success_count = len(news_items) - failed_count
        
        detail_file = os.path.join(detail_dir, f"{target_str}_detail{ext}")
        
        if use_md:
            detail = format_md_detail(date_str, news_items)
        else:
            detail = format_txt_detail(date_str, news_items)
        
        with open(detail_file, "w", encoding="utf-8") as f:
            f.write(detail)
        
        result['detail_file'] = detail_file
        result['success_count'] = success_count
        result['failed_count'] = failed_count
    
    return result, None

def fetch_month(year, month, use_md=False, fetch_detail=False):
    month_str = f"{year}年{month:02d}月"
    print(f"\n{'='*60}")
    print(f"开始下载 {month_str} 的新闻联播")
    print(f"{'='*60}")
    
    days_in_month = calendar.monthrange(year, month)[1]
    
    success_days = 0
    failed_days = 0
    total_news = 0
    total_detail_success = 0
    total_detail_failed = 0
    
    for day in range(1, days_in_month + 1):
        date_str = f"{year}年{month:02d}月{day:02d}日"
        print(f"\n[{day}/{days_in_month}] 正在获取 {date_str}...")
        
        result, error = fetch_single_day(year, month, day, use_md, fetch_detail)
        
        if error:
            print(f"  {error}")
            failed_days += 1
        else:
            success_days += 1
            total_news += result['news_count']
            print(f"  成功获取 {result['news_count']} 条新闻")
            print(f"  简介已保存: {result['summary_file']}")
            
            if fetch_detail:
                if result['success_count'] > 0:
                    print(f"  详情已保存: {result['detail_file']}")
                    print(f"  详情获取成功: {result['success_count']}/{result['news_count']}")
                    total_detail_success += result['success_count']
                    total_detail_failed += result['failed_count']
                else:
                    print(f"  警告: 所有详情获取失败")
                    total_detail_failed += result['news_count']
        
        if day < days_in_month:
            delay = random.uniform(DAY_DELAY_MIN, DAY_DELAY_MAX)
            print(f"  等待 {delay:.1f} 秒后继续...")
            time.sleep(delay)
    
    print(f"\n{'='*60}")
    print(f"{month_str} 下载完成")
    print(f"{'='*60}")
    print(f"成功天数: {success_days}/{days_in_month}")
    print(f"失败天数: {failed_days}")
    print(f"总新闻数: {total_news}")
    if fetch_detail:
        print(f"详情成功: {total_detail_success}")
        if total_detail_failed > 0:
            print(f"详情失败: {total_detail_failed}")
    print(f"文件保存位置: News/{year}/{month:02d}/")

def main():
    use_md = '--md' in sys.argv
    if use_md:
        sys.argv.remove('--md')
    
    if len(sys.argv) < 2:
        print("用法：")
        print("  单日下载：")
        print("    python get_xwlb.py today              # 查看今天的新闻简介")
        print("    python get_xwlb.py yesterday          # 查看昨天的新闻简介")
        print("    python get_xwlb.py 2025-10-01         # 查看指定日期的新闻简介")
        print("    python get_xwlb.py today 1            # 查看今天所有新闻详情")
        print("    python get_xwlb.py today 1 --md       # 生成MD格式文件")
        print("")
        print("  按月下载：")
        print("    python get_xwlb.py month 2025-01      # 下载2025年1月所有新闻简介")
        print("    python get_xwlb.py month 2025-01 1    # 下载2025年1月所有新闻详情")
        print("    python get_xwlb.py month 2025-01 --md # 下载2025年1月所有新闻简介(MD格式)")
        print("")
        print("网络保护机制：")
        print("  - 请求间隔: 0.3-0.8秒随机延迟")
        print("  - 每日间隔: 1.5-3.0秒随机延迟")
        print("  - 并发线程: 5个")
        print("  - 失败重试: 2次")
        return
    
    if sys.argv[1] == "month":
        if len(sys.argv) < 3:
            print("请指定月份，例如: python get_xwlb.py month 2025-01")
            return
        
        month_arg = sys.argv[2]
        try:
            parts = month_arg.split('-')
            year = int(parts[0])
            month = int(parts[1])
            if month < 1 or month > 12:
                print("月份必须在1-12之间")
                return
        except:
            print("月份格式错误，请使用: YYYY-MM，例如 2025-01")
            return
        
        fetch_detail = len(sys.argv) > 3 and sys.argv[3] == '1'
        fetch_month(year, month, use_md, fetch_detail)
        return
    
    date_arg = sys.argv[1]
    
    if date_arg == "today":
        d = datetime.now()
    elif date_arg == "yesterday":
        d = datetime.now() - timedelta(days=1)
    else:
        try:
            if '-' in date_arg:
                parts = date_arg.split('-')
                d = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                d = datetime(int(date_arg[:4]), int(date_arg[4:6]), int(date_arg[6:8]))
        except:
            print("日期格式错误，请使用：YYYY-MM-DD 或 YYYYMMDD")
            return
    
    year, month, day = d.year, d.month, d.day
    date_str = f"{year}年{month:02d}月{day:02d}日"
    target_str = f"{year}{month:02d}{day:02d}"
    
    print(f"正在获取 {date_str} 的新闻联播内容...")
    
    url = f"https://tv.cctv.com/lm/xwlb/day/{target_str}.shtml"
    html = fetch_html(url)
    
    if not html:
        print(f"未找到 {date_str} 的新闻内容")
        return
    
    news_items = parse_day_page(html)
    if not news_items:
        print(f"未找到 {date_str} 的新闻内容")
        return
    
    summary_dir, detail_dir = get_output_dirs(year, month)
    ext = ".md" if use_md else ".txt"
    summary_file = os.path.join(summary_dir, f"{target_str}_summary{ext}")
    detail_file = os.path.join(detail_dir, f"{target_str}_detail{ext}")
    
    if use_md:
        summary = format_md_summary(date_str, news_items)
    else:
        summary = format_summary(date_str, news_items)
    
    print(summary)
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"\n简介已保存到: {summary_file}")
    
    if len(sys.argv) > 2:
        print(f"\n正在并发获取所有新闻的详细内容（{MAX_WORKERS}线程）...")
        
        failed_count = fetch_all_details_concurrent(news_items)
        
        success_count = len(news_items) - failed_count
        
        if success_count == 0:
            print(f"\n警告: 所有 {len(news_items)} 条新闻详情获取失败！")
            print("可能原因: 网络问题或服务器暂时不可用，请稍后重试。")
            return
        
        if failed_count > 0:
            print(f"\n提示: {failed_count} 条新闻详情获取失败，已跳过。")
        
        if use_md:
            detail = format_md_detail(date_str, news_items)
        else:
            detail = format_txt_detail(date_str, news_items)
        
        with open(detail_file, "w", encoding="utf-8") as f:
            f.write(detail)
        print(f"\n详情已保存到: {detail_file}")
        print(f"成功获取 {success_count}/{len(news_items)} 条新闻详情。")

if __name__ == "__main__":
    main()
