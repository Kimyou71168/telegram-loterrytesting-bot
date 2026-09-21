import itertools
import os
import re
import requests
from collections import Counter
from flask import Flask, request

# 🔑 Telegram Bot Token
BOT_TOKEN = "8961460379:AAFO-Qszn24e-upnZVHCjQyj6hKcMpTZQu4"
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

app = Flask(__name__)

# 💵 អត្រាសងរង្វាន់
PAYOUT_2D = 90
PAYOUT_3D = 800

# Memory Storage
USER_TICKETS = {}
PENDING_RESULT_HEADERS = {}
USER_RESULTS = {}


def normalize_text(text):
    if not text:
        return ""
    text = text.upper().strip().replace("\xa0", " ")
    text = re.sub(r"\b0(\d:\d{2})", r"\1", text)
    return text


def extract_time_and_period(first_line):
    clean_line = normalize_text(first_line)
    match = re.search(
        r"(\d{1,2})\s*[:\.]\s*(\d{2})\s*(AM|PM)?", clean_line, re.IGNORECASE
    )
    if not match:
        return "EVENING", clean_line

    h = int(match.group(1))
    m = int(match.group(2))
    ampm = match.group(3).upper() if match.group(3) else ""

    if ampm == "PM" and h < 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0

    if h == 13 and m == 30:
        period = "1:30PM"
    elif (
        (h == 18 and m >= 30)
        or h in [19, 20]
        or (h == 6 and m >= 30 and ampm == "PM")
        or (h == 8 and ampm == "PM")
    ):
        period = "EVENING"
    else:
        period = "DAYTIME"

    return period, f"{h}:{m:02d}"


def get_post_info(post_name, period="EVENING"):
    p = post_name.upper().replace(" ", "")

    if period == "EVENING":
        if p in ["ABCD", "4P2"]:
            return 7, 6, "ប៉ុស្តិ៍ ABCD/4P2 (2D:7P / 3D:6P)", ["4P2"]
        if p == "A2":
            return 4, 3, "ប៉ុស្តិ៍ A2 (2D:4P / 3D:3P)", ["A2"]
        if p in ["BCD", "BCDF"]:
            cnt = len(p)
            return cnt, cnt, f"ប៉ុស្តិ៍ {p} ({cnt}P)", list(p)
        if p in ["LO", "LO3"]:
            return 32, 25, "ប៉ុស្តិ៍ LO3 (2D:32P / 3D:25P)", ["LO"]

    elif period == "1:30PM":
        if p in ["LO", "LO1"]:
            return 20, 16, "ប៉ុស្តិ៍ LO1 (2D:20P / 3D:16P)", ["LO"]
        if p in ["LOF", "LO1F", "LOF1"]:
            return 21, 17, "ប៉ុស្តិ៍ LO1F (2D:21P / 3D:17P)", ["LO"]

    if p in ["ABCD", "4P"]:
        return 4, 4, "ប៉ុស្តិ៍ ABCD/4P (2D:4P / 3D:4P)", ["A", "B", "C", "D"]
    if p in ["ABCDF", "5P"]:
        return 5, 5, "ប៉ុស្តិ៍ ABCDF/5P (2D:5P / 3D:5P)", ["A", "B", "C", "D", "F"]
    if p in ["LO", "LO2"]:
        return 23, 19, "ប៉ុស្តិ៍ LO2 (2D:23P / 3D:19P)", ["LO"]
    if p in ["LOF", "LO2F", "LOF2", "LO2+F"]:
        return 24, 20, "ប៉ុស្តិ៍ LO2F (2D:24P / 3D:20P)", ["LO"]

    if p == "4P2":
        return 7, 6, "ប៉ុស្តិ៍ 4P2 (2D:7P / 3D:6P)", ["4P2"]

    if re.match(r"^[A-Z]+$", p):
        cnt = len(p)
        return cnt, cnt, f"ប៉ុស្តិ៍ {p} ({cnt}P)", list(p)

    return 1, 1, f"ប៉ុស្តិ៍ {p} (1P)", [p]


def is_valid_post_header(text_line):
    clean = text_line.upper().replace(" ", "")
    valid_keys = [
        "ABCD",
        "ABCDF",
        "4P",
        "5P",
        "4P2",
        "A2",
        "BCD",
        "LO",
        "LOF",
        "LO1",
        "LO1F",
        "LOF1",
        "LO2",
        "LO2F",
        "LOF2",
        "LO3",
    ]
    if clean in valid_keys or re.match(r"^[A-Z]+$", clean):
        return True
    return False


def parse_entry(entry_str):
    entry_str = normalize_text(entry_str)
    if not entry_str:
        return None

    if "X" in entry_str or "×" in entry_str or "*" in entry_str:
        parts = re.split(r"[xX×\*]", entry_str)
        if len(parts) == 2:
            num_str = parts[0].replace(" ", "").strip()
            price_str = parts[1].replace(" ", "").strip()
            if num_str.isdigit() and price_str.isdigit():
                price = int(price_str)
                num_len = len(num_str)
                perms = set(
                    ["".join(p) for p in itertools.permutations(num_str)]
                )
                cost = len(perms) * price
                type_key = "2d" if num_len == 2 else "3d"
                return {
                    "type": type_key,
                    "cost": cost,
                    "num": int(num_str),
                    "raw_num": num_str,
                    "price": price,
                    "is_x": True,
                    "perms": perms,
                    "category": "mul",
                    "detail": f"  • {num_str}x{price:,} = {len(perms)} លេខ x {price:,} = {cost:,}",
                }

    elif ">" in entry_str or ")" in entry_str:
        normalized_str = entry_str.replace(")", ">")

        range_match = re.search(
            r"^(\d+)\s*>\s*(\d+)[\.:\s]\s*(\d+)$", normalized_str
        )
        if range_match:
            start_num, end_num, price_str = (
                range_match.group(1),
                range_match.group(2),
                range_match.group(3),
            )
            if len(start_num) == len(end_num):
                s_int, e_int = int(start_num), int(end_num)
                if s_int <= e_int:
                    price = int(price_str)
                    num_len = len(start_num)
                    fmt = f"0{num_len}d"
                    range_nums = [
                        format(i, fmt) for i in range(s_int, e_int + 1)
                    ]
                    cost = len(range_nums) * price
                    type_key = "2d" if num_len == 2 else "3d"
                    return {
                        "type": type_key,
                        "cost": cost,
                        "num": int(start_num),
                        "range_nums": range_nums,
                        "price": price,
                        "is_range": True,
                        "category": "mul",
                        "detail": f"  • {start_num}>{end_num} {price:,} = {len(range_nums)} លេខ x {price:,} = {cost:,}",
                    }

        head_match = re.search(r"^(\d+)\s*>\s*(\d+)$", normalized_str)
        if head_match:
            num_str, price_str = head_match.group(1), head_match.group(2)
            price = int(price_str)
            num_len = len(num_str)
            cost = 10 * price
            type_key = "2d" if num_len <= 2 else "3d"
            base_digit = num_str[0] if num_len == 2 else num_str[:2]
            nums_in_head = [f"{base_digit}{d}" for d in range(10)]
            return {
                "type": type_key,
                "cost": cost,
                "num": int(num_str),
                "range_nums": nums_in_head,
                "price": price,
                "is_head": True,
                "category": "mul",
                "detail": f"  • {num_str}) {price:,} = 10 លេខ x {price:,} = {cost:,}",
            }

    else:
        normal_match = re.search(r"^(\d+)\s*[\.:\s]\s*(\d+)$", entry_str)
        if normal_match:
            num_str, price_str = normal_match.group(1), normal_match.group(2)
            price = int(price_str)
            num_len = len(num_str)
            type_key = "2d" if num_len == 2 else "3d"
            return {
                "type": type_key,
                "cost": price,
                "num": int(num_str),
                "raw_num": num_str,
                "price": price,
                "is_normal": True,
                "category": "normal",
                "detail": f"  • {num_str}:{price:,} = {price:,}",
            }

    return None


def show_all_bot_info():
    msg = [
        "🤖 ព័ត៌មានទម្រង់លេខ និងប៉ុស្តិ៍ដែល Bot ស្គាល់ទាំងអស់ 🤖",
        "===================================\n",
        "💡 ១. ទម្រង់សរសេរលេខចាក់ស្គាល់គ្រប់ទម្រង់៖\n",
        "🔹 ទម្រង់លេខស្មើ៖",
        "  • 50:100 | 50.100 | 50 100 ",
        "  ➔ គណនា៖ 50 ចំនួន 100 រៀល\n",
        "🔹 ទម្រង់លេខគុណ៖",
        "  • 570X1500 | 570x 1500 | 570*1500",
        "  ➔ គណនា៖ គុណត្រឡប់ 570 (6 លេខ) x 1,500 រៀល = 9,000 រៀល\n",
        "🔹 ទម្រង់លេខរត់ / ចន្លោះ (> )៖",
        "  • 10>15.100 | 10>15. 100 | 10>15:100 | 10>15: 100 | 10>15 100",
        "  ➔ គណនា៖ លេខរត់ 10 ដល់ 15 (6 លេខ) x 100 រៀល = 600 រៀល\n",
        "🔹 ទម្រង់លេខក្បាល (> / ) )៖",
        "  • 50) 2500 | 50)2500 | 50>2500",
        "  ➔ គណនា៖ ក្បាល 5 (50 ដល់ 59 ស្មើ 10 លេខ) x 2,500 រៀល = 25,000 រៀល\n",
        "===================================",
        "💡 ២. ព័ត៌មានប៉ុស្តិ៍ និងមេគុណ (វាយ 'LO' តែមួយកំណត់ស្វ័យប្រវត្តិ)៖\n",
        "☀️ វេនថ្ងៃធម្មតា (8:30 AM - 5:30 PM)៖",
        "  • 4P / ABCD ៖ 2D: 4P | 3D: 4P",
        "  • 5P / ABCDF ៖ 2D: 5P | 3D: 5P",
        "  • LO / LO2 ៖ 2D: 23P | 3D: 19P",
        "  • LO2F / LOF ៖ 2D: 24P | 3D: 20P\n",
        "🌤️ វេនពិសេស (1:30 PM)៖",
        "  • LO / LO1 ៖ 2D: 20P | 3D: 16P",
        "  • LO1F / LOF ៖ 2D: 21P | 3D: 17P\n",
        "🌙 វេនយប់ (6:30 PM - 8:30 PM)៖",
        "  • 4P2 / ABCD ៖ 2D: 7P | 3D: 6P",
        "  • A2 ៖ 2D: 4P | 3D: 3P",
        "  • LO / LO3 ៖ 2D: 32P | 3D: 25P\n",
        "🔤 ប៉ុស្តិ៍អក្សររាយ៖",
        "  • ស្គាល់អក្សរ A ដល់ Z ទាំងអស់ (ឧ. A, B, BCD...)\n",
        "🗑️ របៀបលុបទិន្នន័យ៖",
        "  • វាយ 'លុប 4:30PM' ➔ លុបតែម៉ោង 4:30PM មួយប៉ុណ្ណោះ",
        "  • វាយ 'លុប' ➔ លុបទិន្នន័យទាំងអស់\n",
        "💵 អត្រាសងរង្វាន់៖ 2D 1X90 | 3D 1X800",
    ]
    return "\n".join(msg)


def parse_result_multi_format(text):
    results = {}
    lines = text.strip().split("\n")
    current_post = None

    a_2d_direct = []
    a_3d_direct = []

    for line in lines:
        line = line.strip().replace("\xa0", " ")
        if not line:
            continue

        match_post = re.match(r"^([A-Za-z0-9]+)\s*[\-:\.\s](.*)$", line)

        if match_post and not line.startswith("-"):
            p_candidate = match_post.group(1).upper()
            content = match_post.group(2).strip()

            if p_candidate not in ["2D", "3D", "លទ្ធផល"]:
                current_post = p_candidate
                if current_post not in results:
                    results[current_post] = {"2d": [], "3d": []}

                nums = re.findall(r"\d+", content)
                for n in nums:
                    if len(n) == 2:
                        results[current_post]["2d"].append(n)
                        if current_post == "A":
                            a_2d_direct.append(n)
                    elif len(n) == 3:
                        results[current_post]["3d"].append(n)
                        if current_post == "A":
                            a_3d_direct.append(n)
                    elif len(n) >= 4:
                        d2, d3 = n[-2:], n[-3:]
                        results[current_post]["2d"].append(d2)
                        results[current_post]["3d"].append(d3)
                        if current_post == "A":
                            a_2d_direct.append(d2)
                            a_3d_direct.append(d3)
                continue

        if re.match(r"^[A-Za-z0-9]+$", line):
            p_name = line.upper()
            if p_name not in ["2D", "3D", "លទ្ធផល"]:
                current_post = p_name
                if current_post not in results:
                    results[current_post] = {"2d": [], "3d": []}
                continue

        nums = re.findall(r"\d+", line)
        if current_post and nums:
            for n in nums:
                if len(n) == 2:
                    results[current_post]["2d"].append(n)
                    if current_post == "A":
                        a_2d_direct.append(n)
                elif len(n) == 3:
                    results[current_post]["3d"].append(n)
                    if current_post == "A":
                        a_3d_direct.append(n)
                elif len(n) >= 4:
                    d2, d3 = n[-2:], n[-3:]
                    results[current_post]["2d"].append(d2)
                    results[current_post]["3d"].append(d3)
                    if current_post == "A":
                        a_2d_direct.append(d2)
                        a_3d_direct.append(d3)

    if a_2d_direct or a_3d_direct:
        a_3d_tails = [x[-2:] for x in a_3d_direct[:3]]

        results["A2"] = {
            "2d": a_2d_direct[:4],
            "3d": a_3d_direct[:3],
        }

        b_2d = results.get("B", {}).get("2d", [])
        c_2d = results.get("C", {}).get("2d", [])
        d_2d = results.get("D", {}).get("2d", [])

        b_3d = results.get("B", {}).get("3d", [])
        c_3d = results.get("C", {}).get("3d", [])
        d_3d = results.get("D", {}).get("3d", [])

        results["4P2"] = {
            "2d": a_2d_direct[:4] + a_3d_tails + b_2d + c_2d + d_2d,
            "3d": a_3d_direct[:3] + b_3d + c_3d + d_3d,
        }

    return results


def build_analysis_section(all_5p_2d, all_5p_3d, lo_2d, lo_3d, group_title):
    sec = [f"==================================="]
    sec.append(f"📌 {group_title}")
    sec.append(f"===================================")

    sec.append("🏆 ១. ស្ថិតិលេខដែលបានចេញសរុបរួម 5P (ABCDF) ៖")
    sec.append("-----------------------------------")
    if all_5p_2d or all_5p_3d:
        c_5p_2d = Counter(all_5p_2d)
        c_5p_3d = Counter(all_5p_3d)

        str_5p_2d = (
            " , ".join([f"{item[0]} ({item[1]}ដង)" for item in c_5p_2d.items()])
            if all_5p_2d
            else "មិនទាន់ចេញ"
        )
        str_5p_3d = (
            " , ".join([f"{item[0]} ({item[1]}ដង)" for item in c_5p_3d.items()])
            if all_5p_3d
            else "មិនទាន់ចេញ"
        )

        sec.append(f"🔹 **លេខ 2D 5P** ៖ {str_5p_2d}")
        sec.append(f"🔹 **លេខ 3D 5P** ៖ {str_5p_3d}\n")
    else:
        sec.append("  • មិនទាន់មានទិន្នន័យលេខចេញ 5P ទេ។\n")

    sec.append("📍 ២. ស្ថិតិលេខដែលបានចេញសរុបរួមក្នុងប៉ុស្តិ៍ Lo ៖")
    sec.append("-----------------------------------")
    if lo_2d or lo_3d:
        c_lo_2d = Counter(lo_2d)
        c_lo_3d = Counter(lo_3d)

        str_lo_2d = (
            " , ".join([f"{item[0]} ({item[1]}ដង)" for item in c_lo_2d.items()])
            if lo_2d
            else "មិនទាន់ចេញ"
        )
        str_lo_3d = (
            " , ".join([f"{item[0]} ({item[1]}ដង)" for item in c_lo_3d.items()])
            if lo_3d
            else "មិនទាន់ចេញ"
        )

        sec.append(f"🔹 **លេខ 2D Lo** ៖ {str_lo_2d}")
        sec.append(f"🔹 **លេខ 3D Lo** ៖ {str_lo_3d}\n")
    else:
        sec.append("  • មិនទាន់មានទិន្នន័យលេខចេញ Lo ទេ។\n")

    sec.append("🎯 ៣. ការវិភាគតម្រុយលេខសម្រាប់តារាង 5P ៖")
    sec.append("-----------------------------------")
    if all_5p_2d:
        ten_counts_5p = Counter([n[0] + "0" for n in all_5p_2d if len(n) == 2])
        all_tens_digits = [str(i) for i in range(10)]
        sorted_tens_5p = sorted(
            all_tens_digits, key=lambda d: ten_counts_5p.get(d + "0", 0)
        )
        t1, t2 = sorted_tens_5p[0], sorted_tens_5p[1]

        rec_5p_2d = [f"{t1}2", f"{t1}5", f"{t1}7", f"{t1}8", f"{t2}5", f"{t2}8"]
        rec_5p_3d = [f"{t1}25X", f"{t1}58X", f"{t2}28X"]

        sec.append(f"👉 **2D 5P សង្ឃឹមខ្ពស់** ៖ ខ្ទង់ {t1}0 | ខ្ទង់ {t2}0")
        sec.append(f"✦ លេខរាយ ២ខ្ទង់ ៖ {', '.join(rec_5p_2d)}")
        sec.append(
            f"👉 **3D 5P ក្បាលសង្ឃឹមខ្ពស់** ៖ ក្បាល {t1}XX | ក្បាល {t2}XX"
        )
        sec.append(f"💰 លេខរាយ ៣ខ្ទង់ (គុណX) ៖ {', '.join(rec_5p_3d)}\n")
    else:
        sec.append("  • មិនទាន់មានទិន្នន័យគ្រប់គ្រាន់សម្រាប់វិភាគ 5P ទេ។\n")

    sec.append("🎯 ៤. ការវិភាគតម្រុយលេខសម្រាប់ប៉ុស្តិ៍ Lo ៖")
    sec.append("-----------------------------------")
    if lo_2d:
        ten_counts_lo = Counter([n[0] + "0" for n in lo_2d if len(n) == 2])
        all_tens_digits = [str(i) for i in range(10)]
        sorted_tens_lo = sorted(
            all_tens_digits, key=lambda d: ten_counts_lo.get(d + "0", 0)
        )
        p1, p2 = sorted_tens_lo[0], sorted_tens_lo[1]

        lo_rec_2d = [f"{p1}2", f"{p1}3", f"{p1}5", f"{p1}8", f"{p2}5", f"{p2}7"]
        lo_rec_3d = [f"{p1}25X", f"{p1}58X", f"{p2}28X"]

        sec.append(f"👉 **2D Lo សង្ឃឹមខ្ពស់** ៖ ខ្ទង់ {p1}0 | ខ្ទង់ {p2}0")
        sec.append(f"✦ លេខរាយ ២ខ្ទង់ ៖ {', '.join(lo_rec_2d)}")
        sec.append(
            f"👉 **3D Lo ក្បាលសង្ឃឹមខ្ពស់** ៖ ក្បាល {p1}XX | ក្បាល {p2}XX"
        )
        sec.append(f"💰 លេខរាយ ៣ខ្ទង់ (គុណX) ៖ {', '.join(lo_rec_3d)}\n")
    else:
        sec.append("  • មិនទាន់មានទិន្នន័យប៉ុស្តិ៍ Lo គ្រប់គ្រាន់សម្រាប់វិភាគទេ។\n")

    return sec


def generate_win_analysis(chat_id):
    user_res = USER_RESULTS.get(chat_id, {})
    if not user_res:
        return "⚠️ មិនទាន់មានទិន្នន័យលទ្ធផលដែលបានបញ្ចូលក្នុងថ្ងៃនេះនៅឡើយទេ។\nសូមបញ្ចូលលទ្ធផលជាមុនសិនដើម្បីឱ្យប្រព័ន្ធធ្វើការវិភាគ!"

    g1_5p_2d, g1_5p_3d = [], []
    g1_lo_2d, g1_lo_3d = [], []

    g2_5p_2d, g2_5p_3d = [], []
    g2_lo_2d, g2_lo_3d = [], []

    for header, res_text in user_res.items():
        parsed = parse_result_multi_format(res_text)
        header_upper = header.upper().replace(" ", "")

        is_g2 = "4:30" in header_upper or "6:30" in header_upper

        p_map = {
            "A": {"2d": [], "3d": []},
            "B": {"2d": [], "3d": []},
            "C": {"2d": [], "3d": []},
            "D": {"2d": [], "3d": []},
            "F": {"2d": [], "3d": []},
            "LO": {"2d": [], "3d": []},
        }

        for p, data in parsed.items():
            if p in p_map:
                p_map[p]["2d"].extend(data["2d"])
                p_map[p]["3d"].extend(data["3d"])

        if is_g2:
            for p_name in ["A", "B", "C", "D", "F"]:
                g2_5p_2d.extend(p_map[p_name]["2d"])
                g2_5p_3d.extend(p_map[p_name]["3d"])
            g2_lo_2d.extend(p_map["LO"]["2d"])
            g2_lo_3d.extend(p_map["LO"]["3d"])
        else:
            for p_name in ["A", "B", "C", "D", "F"]:
                g1_5p_2d.extend(p_map[p_name]["2d"])
                g1_5p_3d.extend(p_map[p_name]["3d"])
            g1_lo_2d.extend(p_map["LO"]["2d"])
            g1_lo_3d.extend(p_map["LO"]["3d"])

    out = ["📊 តារាងវិភាគ និងស្ថិតិលទ្ធផលចែកជា ២ ក្រុមដាច់ដោយឡែក"]

    sec1 = build_analysis_section(
        g1_5p_2d,
        g1_5p_3d,
        g1_lo_2d,
        g1_lo_3d,
        "ក្រុមទី ១ ៖ ម៉ោង (8:30AM ដល់ 3:30PM, 5:30PM, 7:30PM, 8:30PM)",
    )
    out.extend(sec1)

    sec2 = build_analysis_section(
        g2_5p_2d,
        g2_5p_3d,
        g2_lo_2d,
        g2_lo_3d,
        "ក្រុមទី ២ ៖ ម៉ោង (4:30PM និង 6:30PM)",
    )
    out.extend(sec2)

    out.append("===================================")
    out.append("         🙏 សូមជូនពរសំណាងល្អ 🙏")

    return "\n".join(out)


def check_single_ticket_win_details(ticket_text, result_text, header_info):
    period, _ = extract_time_and_period(header_info)
    results = parse_result_multi_format(result_text)

    lines = ticket_text.strip().split("\n")
    current_post = "5P"

    sum_2d_stake = 0
    sum_3d_stake = 0
    win_2d_payout = 0
    win_3d_payout = 0

    hit_2d_nums = []
    hit_2d_stake = 0
    hit_3d_nums = []
    hit_3d_stake = 0

    preview_items = []

    for line in lines[1:]:
        line_clean = line.strip().upper().replace("\xa0", " ")
        if not line_clean:
            continue

        parsed = parse_entry(line_clean)
        if parsed:
            m_2d, m_3d, _, target_posts = get_post_info(current_post, period)

            if parsed["type"] == "2d":
                sum_2d_stake += parsed["cost"] * m_2d
            elif parsed["type"] == "3d":
                sum_3d_stake += parsed["cost"] * m_3d

            if len(preview_items) < 3:
                preview_items.append(line_clean)

            if results:
                for p_name in target_posts:
                    if p_name in results:
                        p_vals = results[p_name]
                        win_nums_list = list(p_vals[parsed["type"]])

                        target_nums = []
                        if parsed.get("is_normal"):
                            target_nums = [parsed["raw_num"]]
                        elif parsed.get("is_x"):
                            target_nums = list(parsed["perms"])
                        elif parsed.get("is_range") or parsed.get("is_head"):
                            target_nums = parsed["range_nums"]

                        for t_num in target_nums:
                            hit_count = win_nums_list.count(t_num)
                            if hit_count > 0:
                                win_stake = parsed["price"] * hit_count
                                payout = win_stake * (
                                    PAYOUT_2D
                                    if parsed["type"] == "2d"
                                    else PAYOUT_3D
                                )
                                if parsed["type"] == "2d":
                                    win_2d_payout += payout
                                    hit_2d_nums.append(t_num)
                                    hit_2d_stake += win_stake
                                else:
                                    win_3d_payout += payout
                                    hit_3d_nums.append(t_num)
                                    hit_3d_stake += win_stake
        else:
            check_post = line_clean.replace(" ", "")
            if is_valid_post_header(check_post):
                current_post = check_post
                if len(preview_items) < 3:
                    preview_items.append(current_post)

    total_cost = sum_2d_stake + sum_3d_stake
    total_win = win_2d_payout + win_3d_payout

    preview_str = " | ".join(preview_items)
    if len(lines) - 1 > 3:
        preview_str += "..."

    return {
        "2d_cost": sum_2d_stake,
        "3d_cost": sum_3d_stake,
        "total_cost": total_cost,
        "win_2d_payout": win_2d_payout,
        "win_3d_payout": win_3d_payout,
        "hit_2d_nums": hit_2d_nums,
        "hit_2d_stake": hit_2d_stake,
        "hit_3d_nums": hit_3d_nums,
        "hit_3d_stake": hit_3d_stake,
        "total_win": total_win,
        "preview": preview_str,
    }


def show_stored_tickets_summary(chat_id):
    user_data = USER_TICKETS.get(chat_id, {})
    if not user_data:
        return "⚠️ មិនទាន់មានទិន្នន័យសន្លឹកទិញត្រូវបានរក្សាទុកនៅឡើយទេ។\nសូមផ្ញើសន្លឹកចាក់ចូលមុននឹងធ្វើការ Check!"

    out = ["📊 តារាងទិន្នន័យសន្លឹកទិញ និងប្រាក់ត្រូវរង្វាន់"]
    out.append("-----------------------------------")

    total_all_tickets = 0
    grand_total_all_cost = 0
    grand_total_all_win = 0

    for header_info, tickets in user_data.items():
        num_tickets = len(tickets)
        total_all_tickets += num_tickets
        period_2d_cost = 0
        period_3d_cost = 0
        period_2d_win_stake = 0
        period_3d_win_stake = 0
        period_2d_win_payout = 0
        period_3d_win_payout = 0

        result_text = USER_RESULTS.get(chat_id, {}).get(header_info, "")

        ticket_summary_list = []
        for t_text in tickets:
            details = check_single_ticket_win_details(
                t_text, result_text, header_info
            )
            ticket_summary_list.append(details)

            period_2d_cost += details["2d_cost"]
            period_3d_cost += details["3d_cost"]
            period_2d_win_stake += details["hit_2d_stake"]
            period_3d_win_stake += details["hit_3d_stake"]
            period_2d_win_payout += details["win_2d_payout"]
            period_3d_win_payout += details["win_3d_payout"]

        period_total_cost = period_2d_cost + period_3d_cost
        period_total_win = period_2d_win_payout + period_3d_win_payout

        grand_total_all_cost += period_total_cost
        grand_total_all_win += period_total_win

        out.append(
            f"📅 {header_info} សរុបមាន {num_tickets}សន្លឹក = {period_total_cost:,} រៀល\n"
        )

        for idx, d in enumerate(ticket_summary_list, start=1):
            out.append(f"សន្លឹកទី{idx}")
            out.append(f"  • {d['preview']}")
            out.append(f"  2D: {d['2d_cost']:,} រៀល")
            out.append(f"  3D: {d['3d_cost']:,} រៀល")
            out.append(f"  ❇️ សរុបលុយចាក់ = {d['total_cost']:,} រៀល")

            out.append("📌 លេខត្រូវរង្វាន់៖")
            if d["total_win"] > 0:
                if d["hit_2d_nums"]:
                    nums_str = " ,".join(d["hit_2d_nums"])
                    out.append(
                        f"  2D: {nums_str} = ({d['hit_2d_stake']:,} រៀល)"
                    )
                if d["hit_3d_nums"]:
                    nums_str = " ,".join(d["hit_3d_nums"])
                    out.append(
                        f"  3D: {nums_str} = ({d['hit_3d_stake']:,} រៀល)"
                    )

                out.append("🖐️ សរុបលុយរង្វាន់")
                if d["win_2d_payout"] > 0:
                    out.append(f"  2D: {d['win_2d_payout']:,} រៀល")
                if d["win_3d_payout"] > 0:
                    out.append(f"  3D: {d['win_3d_payout']:,} រៀល")
            else:
                out.append("  ❌ មិនមានលេខត្រូវរង្វាន់ទេ")

            out.append(f"  👉 សរុបរង្វាន់សន្លឹកទី{idx} = {d['total_win']:,} រៀល\n")

        out.append("----------------------------------")
        out.append(f"🏆 សរុបវេន {header_info} ({num_tickets}សន្លឹក)")
        out.append(f"  ចាក់2D: {period_2d_cost:,} រៀល")
        out.append(f"  ចាក់3D: {period_3d_cost:,} រៀល")
        out.append(f"  ❇️សរុបចាក់ = {period_total_cost:,} រៀល")
        out.append(f"  រង្វាន់2D: {period_2d_win_stake:,} រៀល")
        out.append(f"  រង្វាន់3D: {period_3d_win_stake:,} រៀល")
        out.append(f"  💵 សរុបរង្វាន់ = {period_total_win:,} រៀល")
        out.append("=======================")

    out.append(f"📈 សរុបទាំងអស់ ៖ {total_all_tickets} សន្លឹក")
    out.append(f"💵 សរុបចាក់គ្រប់វេន = {grand_total_all_cost:,} រៀល")
    out.append(f"💰 សរុបរង្វាន់គ្រប់វេន = {grand_total_all_win:,} រៀល\n")
    out.append("         🙏 សូមជូនពរសំណាងល្អ 🙏")
    return "\n".join(out)


def check_ticket_win(chat_id, tickets_list, result_text, header_info):
    period, _ = extract_time_and_period(header_info)
    results = parse_result_multi_format(result_text)
    if not results:
        return f"❌ លទ្ធផល ({header_info})៖ មិនមានទិន្នន័យអត្ថបទត្រូវផ្ទៀងផ្ទាត់ទេ។"

    win_groups = {}
    sum_2d_stake = 0
    sum_3d_stake = 0

    for ticket_text in tickets_list:
        lines = ticket_text.strip().split("\n")
        current_post = "5P"

        for line in lines:
            line_clean = line.strip().upper().replace("\xa0", " ")
            if not line_clean:
                continue

            parsed = parse_entry(line_clean)
            if parsed:
                m_2d, m_3d, label, target_posts = get_post_info(
                    current_post, period
                )

                for p_name in target_posts:
                    if p_name in results:
                        p_vals = results[p_name]
                        win_nums_list = list(p_vals[parsed["type"]])

                        target_nums = []
                        if parsed.get("is_normal"):
                            target_nums = [parsed["raw_num"]]
                        elif parsed.get("is_x"):
                            target_nums = list(parsed["perms"])
                        elif parsed.get("is_range") or parsed.get("is_head"):
                            target_nums = parsed["range_nums"]

                        for t_num in target_nums:
                            hit_count = win_nums_list.count(t_num)
                            if hit_count > 0:
                                group_title = f"GROUP {current_post.upper()}"
                                if group_title not in win_groups:
                                    win_groups[group_title] = []

                                type_label = parsed["type"].upper()
                                win_stake = parsed["price"] * hit_count
                                win_groups[group_title].append(
                                    f"{type_label} ត្រូវលេខ {t_num} = {win_stake:,}"
                                )

                                if parsed["type"] == "2d":
                                    sum_2d_stake += win_stake
                                else:
                                    sum_3d_stake += win_stake
            else:
                check_post = line_clean.replace(" ", "")
                if is_valid_post_header(check_post):
                    current_post = check_post

    if not win_groups:
        return f"❌ លទ្ធផល ({header_info})៖ មិនមានលេខត្រូវរង្វាន់ទេ។\n\n         🙏 សូមជូនពរសំណាងល្អ 🙏"

    output = [f"🎉 លទ្ធផលលេខត្រូវរង្វាន់ ({header_info})"]
    output.append(
        f"ℹ️ (អាត្រារង្វាន់៖ 2D 1X{PAYOUT_2D} | 3D 1X{PAYOUT_3D})"
    )
    output.append("-----------------------------")

    for g_title, items in win_groups.items():
        output.append(f"  • {g_title}")
        for item in items:
            output.append(f"    {item}")

    output.append("-----------------------------")
    output.append("📌 ត្រូវរង្វាន់សរុប៖")

    total_2d_payout = sum_2d_stake * PAYOUT_2D
    total_3d_payout = sum_3d_stake * PAYOUT_3D
    grand_total_payout = total_2d_payout + total_3d_payout

    if sum_2d_stake > 0:
        output.append(
            f"  • 2D = {sum_2d_stake:,} X {PAYOUT_2D} = {total_2d_payout:,} រៀល"
        )
    if sum_3d_stake > 0:
        output.append(
            f"  • 3D = {sum_3d_stake:,} X {PAYOUT_3D} = {total_3d_payout:,} រៀល"
        )

    output.append("-----------------------------")
    output.append(f"👉 សរុបប្រាក់រង្វាន់ = {grand_total_payout:,} រៀល\n")
    output.append("         🙏 សូមជូនពរសំណាងល្អ 🙏")

    return "\n".join(output)


def calculate_lottery(input_text, header_info):
    period, _ = extract_time_and_period(header_info)
    lines = input_text.strip().split("\n")
    post_groups = {}
    current_post = "5P"

    for line in lines[1:]:
        line_clean = line.strip().upper().replace("\xa0", " ")
        if not line_clean:
            continue

        parsed = parse_entry(line_clean)
        if parsed:
            if current_post not in post_groups:
                post_groups[current_post] = {
                    "2d_items": [],
                    "3d_items": [],
                    "2d_sum": 0,
                    "3d_sum": 0,
                }

            if parsed["type"] == "2d":
                post_groups[current_post]["2d_items"].append(parsed)
                post_groups[current_post]["2d_sum"] += parsed["cost"]
            elif parsed["type"] == "3d":
                post_groups[current_post]["3d_items"].append(parsed)
                post_groups[current_post]["3d_sum"] += parsed["cost"]
        else:
            check_post = line_clean.replace(" ", "")
            if is_valid_post_header(check_post):
                current_post = check_post
                if current_post not in post_groups:
                    post_groups[current_post] = {
                        "2d_items": [],
                        "3d_items": [],
                        "2d_sum": 0,
                        "3d_sum": 0,
                    }

    if not post_groups:
        return None

    sorted_post_order = sorted(post_groups.keys())
    total_2d_all = 0
    total_3d_all = 0
    output_lines = [f"📅 [ {header_info} ]"]

    for post in sorted_post_order:
        data = post_groups[post]
        m_2d, m_3d, label, _ = get_post_info(post, period)

        post_upper = post.upper()
        output_lines.append(f"📦 === GROUP {post_upper} ===")
        output_lines.append(f"📍 {label}")

        if data["2d_items"]:
            sorted_2d = sorted(
                data["2d_items"],
                key=lambda x: (0 if x["category"] == "normal" else 1, x["num"]),
            )
            output_lines.append("🔹 លេខ ២ខ្ទង់:")
            for item in sorted_2d:
                output_lines.append(item["detail"])
            sum_2d_mult = data["2d_sum"] * m_2d
            output_lines.append(
                f"   ↳ សរុប ២ខ្ទង់ = {data['2d_sum']:,} x {m_2d} = {sum_2d_mult:,} រៀល"
            )

        if data["3d_items"]:
            sorted_3d = sorted(
                data["3d_items"],
                key=lambda x: (0 if x["category"] == "normal" else 1, x["num"]),
            )
            output_lines.append("🔹 លេខ ៣ខ្ទង់:")
            for item in sorted_3d:
                output_lines.append(item["detail"])
            sum_3d_mult = data["3d_sum"] * m_3d
            output_lines.append(
                f"   ↳ សរុប ៣ខ្ទង់ = {data['3d_sum']:,} x {m_3d} = {sum_3d_mult:,} រៀល"
            )

        block_2d_total = data["2d_sum"] * m_2d
        block_3d_total = data["3d_sum"] * m_3d
        block_grand_total = block_2d_total + block_3d_total

        total_2d_all += block_2d_total
        total_3d_all += block_3d_total

        output_lines.append(
            f"➡️ សរុបប្រចាំ GROUP {post_upper}: {block_grand_total:,} រៀល\n"
        )

    grand_total = total_2d_all + total_3d_all
    output_lines.append("======================")
    output_lines.append(f"👉 សរុប 2ខ្ទង់ = {total_2d_all:,} រៀល")
    output_lines.append(f"👉 សរុប 3ខ្ទង់ = {total_3d_all:,} រៀល")
    output_lines.append(f"💰 សរុបរួម = {grand_total:,} រៀល\n")
    output_lines.append("         🙏 សូមជូនពរសំណាងល្អ 🙏")

    return "\n".join(output_lines)


def clear_user_tickets(chat_id, target_time=""):
    if not target_time:
        if (chat_id in USER_TICKETS and USER_TICKETS[chat_id]) or (
            chat_id in USER_RESULTS and USER_RESULTS[chat_id]
        ):
            USER_TICKETS[chat_id] = {}
            USER_RESULTS[chat_id] = {}
            if chat_id in PENDING_RESULT_HEADERS:
                del PENDING_RESULT_HEADERS[chat_id]
            return "🗑️ បានលុបទិន្នន័យសន្លឹកទិញ និងប្រវត្តិលទ្ធផលទាំងអស់ជោគជ័យ!"
        return "⚠️ មិនមានទិន្នន័យត្រូវលុបទេ។"

    target_clean = target_time.upper().replace(" ", "")
    deleted_items = []

    if chat_id in USER_TICKETS:
        keys_to_del = [
            k
            for k in USER_TICKETS[chat_id].keys()
            if target_clean in k.upper().replace(" ", "")
        ]
        for k in keys_to_del:
            del USER_TICKETS[chat_id][k]
            deleted_items.append(k)

    if chat_id in USER_RESULTS:
        keys_to_del = [
            k
            for k in USER_RESULTS[chat_id].keys()
            if target_clean in k.upper().replace(" ", "")
        ]
        for k in keys_to_del:
            del USER_RESULTS[chat_id][k]
            if k not in deleted_items:
                deleted_items.append(k)

    if deleted_items:
        return f"🗑️ បានលុបទិន្នន័យសម្រាប់ម៉ោង ({target_time}) ជោគជ័យ!"
    return f"⚠️ មិនរកឃើញទិន្នន័យសម្រាប់ម៉ោង ({target_time}) ដើម្បីលុបទេ។"


def find_matched_tickets(chat_id, header_text):
    user_data = USER_TICKETS.get(chat_id, {})
    if not user_data:
        return [], header_text

    norm_header = normalize_text(header_text)
    date_match = re.search(
        r"(\d{1,2}\s*[\/\.-]\s*\d{1,2}\s*[\/\.-]\s*\d{2,4})", norm_header
    )
    time_match = re.search(
        r"(\d{1,2}\s*[:\.]\s*\d{2}\s*(?:AM|PM)?)", norm_header, re.IGNORECASE
    )

    extracted_date = date_match.group(1).replace(" ", "") if date_match else ""
    extracted_time = time_match.group(1).replace(" ", "") if time_match else ""

    for key, tickets in user_data.items():
        norm_key = normalize_text(key)
        if (extracted_date and extracted_date in norm_key) and (
            extracted_time and extracted_time in norm_key
        ):
            return tickets, key
        if norm_key in norm_header or norm_header in norm_key:
            return tickets, key

    return [], header_text


def send_message(chat_id, text):
    requests.post(
        URL + "sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    )


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        return "OK", 200

    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if chat_id:
        if "photo" in message:
            caption = message.get("caption", "").strip()

            if caption:
                header_info = caption.replace("លទ្ធផល", "").strip()
            elif chat_id in PENDING_RESULT_HEADERS:
                header_info = PENDING_RESULT_HEADERS.pop(chat_id)
            else:
                send_message(
                    chat_id,
                    "⚠️ សូមផ្ញើសារអត្ថបទ 'លទ្ធផល ថ្ងៃ ខែ ឆ្នាំ ម៉ោង' ជាមុនសិន!",
                )
                return "OK", 200

            matched_tickets, actual_header = find_matched_tickets(
                chat_id, header_info
            )

            if chat_id not in USER_RESULTS:
                USER_RESULTS[chat_id] = {}
            USER_RESULTS[chat_id][actual_header] = caption

            if matched_tickets:
                win_result = check_ticket_win(
                    chat_id,
                    matched_tickets,
                    caption if caption else actual_header,
                    actual_header,
                )
                send_message(chat_id, win_result)
            else:
                send_message(
                    chat_id,
                    f"📥 បានរក្សាទុកទិន្នន័យលទ្ធផល ({actual_header}) រួចរាល់!",
                )

            return "OK", 200

        if "text" in message:
            raw_text = message["text"].strip()
            cmd_text = raw_text.lower().strip()

            if cmd_text in ["/win", "win", "ឈ្នះ"]:
                win_msg = generate_win_analysis(chat_id)
                send_message(chat_id, win_msg)
                return "OK", 200

            if cmd_text in ["/see", "see", "មើល", "/show", "show", "បង្ហាញ"]:
                info_msg = show_all_bot_info()
                send_message(chat_id, info_msg)
                return "OK", 200

            if cmd_text in ["/check", "check", "ឆែក", "/tell", "tell", "ប្រាប់"]:
                summary_msg = show_stored_tickets_summary(chat_id)
                send_message(chat_id, summary_msg)
                return "OK", 200

            if (
                cmd_text.startswith("clear")
                or cmd_text.startswith("លុប")
                or cmd_text.startswith("/clear")
            ):
                parts = raw_text.split(maxsplit=1)
                target_time = parts[1].strip() if len(parts) > 1 else ""
                clear_msg = clear_user_tickets(chat_id, target_time)
                send_message(chat_id, clear_msg)
                return "OK", 200

            if raw_text.startswith("លទ្ធផល"):
                header_info = raw_text.replace("លទ្ធផល", "").strip()
                PENDING_RESULT_HEADERS[chat_id] = header_info
                send_message(
                    chat_id,
                    f"📥 បានទទួលសំណើលទ្ធផល ({header_info}) រួចរាល់!\nសូមផ្ញើអត្ថបទតារាងលទ្ធផលមកដើម្បីឱ្យ Bot ផ្ទៀងផ្ទាត់ និងចងចាំទុក។",
                )
                return "OK", 200

            lines = raw_text.split("\n")
            header_info = lines[0].strip()

            is_result_msg = bool(
                re.search(r"-\d+", raw_text) or raw_text.startswith("លទ្ធផល")
            )

            if is_result_msg:
                combined_header = (
                    " ".join([lines[0], lines[1]])
                    if len(lines) > 1
                    else header_info
                )
                matched_tickets, actual_header = find_matched_tickets(
                    chat_id, combined_header
                )

                if chat_id not in USER_RESULTS:
                    USER_RESULTS[chat_id] = {}
                USER_RESULTS[chat_id][actual_header] = raw_text

                if matched_tickets:
                    win_result = check_ticket_win(
                        chat_id, matched_tickets, raw_text, actual_header
                    )
                    send_message(chat_id, win_result)
                else:
                    send_message(
                        chat_id,
                        f"📥 បានរក្សាទុកទិន្នន័យលទ្ធផល ({actual_header}) រួចរាល់!",
                    )

            else:
                result = calculate_lottery(raw_text, header_info)
                if result:
                    if chat_id not in USER_TICKETS:
                        USER_TICKETS[chat_id] = {}
                    if header_info not in USER_TICKETS[chat_id]:
                        USER_TICKETS[chat_id][header_info] = []
                    USER_TICKETS[chat_id][header_info].append(raw_text)

                    send_message(chat_id, result)

    return "OK", 200


@app.route("/")
def index():
    return "Bot status: Active"


if __name__ == "__main__":
    # 🚀 Auto-set Webhook on startup if RENDER_EXTERNAL_URL is available
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        webhook_url = f"{render_url}/{BOT_TOKEN}"
        try:
            res = requests.get(f"{URL}setWebhook?url={webhook_url}")
            print("Auto-set webhook response:", res.json())
        except Exception as e:
            print("Failed to auto-set webhook:", e)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
