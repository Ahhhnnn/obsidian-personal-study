#!/usr/bin/env python3
"""调用 tu-zi.com 图片生成 API 创建图像。"""

import argparse
import json
import sys

import requests

API_BASE = "https://api.tu-zi.com"
API_URL = f"{API_BASE}/v1/images/generations"
TOKEN = "sk-ogSmKNg8rV4M8FHMSIl3LkhFjcO7z67IRph9hziECjLC6Hui"


def generate_image(
    prompt: str,
    model: str = "gpt-image-2",
    size: str = "1024x1024",
    n: int = 1,
    quality: str | None = None,
    response_format: str | None = None,
    style: str | None = None,
    image: list[str] | None = None,
    output: str | None = None,
) -> dict:
    """调用图片生成 API。"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
    }

    if quality:
        payload["quality"] = quality
    if response_format:
        payload["response_format"] = response_format
    if style:
        payload["style"] = style
    if image:
        payload["image"] = image

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()

    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到 {output}")

    return result


def main():
    parser = argparse.ArgumentParser(description="调用 tu-zi.com API 生成图片")
    parser.add_argument("prompt", help="图片描述文本，最长 5000 字符")
    parser.add_argument(
        "-m",
        "--model",
        default="gpt-image-2",
        choices=["gpt-image-2"],
        help="模型名称（默认: gpt-image-2）",
    )
    parser.add_argument(
        "-s",
        "--size",
        default="1024x1024",
        help="图片尺寸，如 1024x1024、3840x2160、auto 等（默认: 1024x1024）",
    )
    parser.add_argument(
        "-n",
        "--number",
        type=int,
        default=1,
        help="生成数量 1-10（默认: 1）",
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=["auto", "low", "medium", "high"],
        help="图片质量（仅 dall-e-3 支持）",
    )
    parser.add_argument(
        "-f",
        "--response-format",
        choices=["url", "b64_json"],
        help="返回格式",
    )
    parser.add_argument(
        "--style",
        choices=["vivid", "natural"],
        help="图片风格（仅 dall-e-3 支持）",
    )
    parser.add_argument(
        "-i",
        "--image",
        nargs="+",
        help="输入图片 URL 或 base64（图生图模式）",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="将结果保存到 JSON 文件",
    )

    args = parser.parse_args()

    try:
        result = generate_image(
            prompt=args.prompt,
            model=args.model,
            size=args.size,
            n=args.number,
            quality=args.quality,
            response_format=args.response_format,
            style=args.style,
            image=args.image,
            output=args.output,
        )

        # 打印结果
        print(f"创建时间: {result.get('created')}")
        for i, item in enumerate(result.get("data", [])):
            url = item.get("url", "N/A")
            print(f"图片 {i + 1}: {url}")

    except requests.HTTPError as e:
        print(f"HTTP 错误: {e}", file=sys.stderr)
        if e.response is not None:
            print(f"响应内容: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"请求错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
