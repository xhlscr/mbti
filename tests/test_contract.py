"""前后端契约一致性检查（离线可跑，不需要启动服务）。

守的是最容易悄悄漂移的三件事：
1. 前端调的路径，后端真的有；
2. 前端引用的组件，文件真的存在；
3. 相对 import 不指向空气。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
ENDPOINTS = BACKEND / "app" / "api" / "v1" / "endpoints"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ROUTE_RE = re.compile(r'@router\.(get|post|patch|put|delete)\(\s*"([^"]*)"')
PREFIX_RE = re.compile(r'APIRouter\([^)]*prefix="([^"]*)"', re.S)
NUXT_BUILTINS = {
    "NuxtPage", "NuxtLayout", "NuxtLink", "NuxtLoadingIndicator", "NuxtErrorBoundary",
    "ClientOnly", "Transition", "TransitionGroup", "KeepAlive", "Teleport", "Suspense",
    "Component",
}

# 构建产物与依赖目录，绝不能参与源码检查
IGNORED_PARTS = {"node_modules", ".nuxt", ".output", ".data", "dist", ".git"}


def iter_frontend(pattern: str):
    """只遍历源码文件，跳过 node_modules / .nuxt / .output 等生成目录。"""
    for path in FRONTEND.glob(pattern):
        if IGNORED_PARTS & set(path.parts):
            continue
        yield path


def backend_routes() -> set[str]:
    routes: set[str] = set()
    for path in ENDPOINTS.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        prefix_match = PREFIX_RE.search(source)
        prefix = prefix_match.group(1) if prefix_match else ""
        for _, route in ROUTE_RE.findall(source):
            full = f"{prefix}{route}" if route else prefix
            routes.add(re.sub(r"\{[^}]+\}", "{}", full.rstrip("/") or "/"))
    routes.add("/healthz")
    return routes


def frontend_paths() -> set[str]:
    source = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    raw = re.findall(r"[`'\"](/[^`'\"$]*)[`'\"]", source)
    raw += re.findall(r"`(/[^`]*)`", source)
    paths = set()
    for item in raw:
        normalized = re.sub(r"\$\{[^}]+\}", "{}", item)
        normalized = re.sub(r"\{[^}]+\}", "{}", normalized).rstrip("/") or "/"
        paths.add(normalized)
    return {p for p in paths if p not in {"/"}}


class ContractTests(unittest.TestCase):
    def test_frontend_api_paths_exist_in_backend(self) -> None:
        routes = backend_routes()
        missing = sorted(p for p in frontend_paths() if p not in routes)
        self.assertEqual(missing, [], f"前端调用了后端不存在的路径：{missing}")

    def test_route_params_are_consistent(self) -> None:
        """同一路径的模板参数数量必须一致，防止 /sessions/{id}/answers 写错层级。"""
        routes = backend_routes()
        for path in frontend_paths():
            self.assertIn(path, routes, f"{path} 未在后端注册")

    def test_component_registry_files_exist(self) -> None:
        registry = (FRONTEND / "components" / "question" / "registry.ts").read_text(encoding="utf-8")
        for rel in re.findall(r"import\('\./([^']+)'\)", registry):
            target = FRONTEND / "components" / "question" / rel
            self.assertTrue(target.exists(), f"registry 指向了不存在的组件：{target.name}")

    def test_template_components_exist(self) -> None:
        names = {p.stem for p in iter_frontend("components/**/*.vue")}
        missing: list[str] = []
        for vue in iter_frontend("**/*.vue"):
            text = vue.read_text(encoding="utf-8")
            # 只看 <template> 块：script 里的 Record<Dim, number> 不是组件
            match = re.search(r"<template>(.*?)</template>", text, re.S)
            if not match:
                continue
            for tag in re.findall(r"<([A-Z][A-Za-z0-9]*)", match.group(1)):
                if tag in NUXT_BUILTINS or tag in names:
                    continue
                missing.append(f"{vue.relative_to(FRONTEND)} -> <{tag}>")
        self.assertEqual(missing, [], f"模板里用了不存在的组件：{missing}")

    def test_relative_imports_resolve(self) -> None:
        broken: list[str] = []
        for file in list(iter_frontend("**/*.ts")) + list(iter_frontend("**/*.vue")):
            text = file.read_text(encoding="utf-8")
            for spec in re.findall(r"from\s+['\"](\.[^'\"]+)['\"]", text):
                base = (file.parent / spec).resolve()
                candidates = [
                    base, base.with_suffix(".ts"), base.with_suffix(".vue"),
                    base / "index.ts", base / "index.vue",
                ]
                if not any(c.exists() for c in candidates):
                    broken.append(f"{file.relative_to(FRONTEND)} -> {spec}")
        self.assertEqual(broken, [], f"相对 import 无法解析：{broken}")

    def test_no_weights_leak_to_frontend(self) -> None:
        """前端不允许出现权重计算：payload 里没有 weights 字段的读取。"""
        offenders = [
            str(p.relative_to(FRONTEND))
            for p in iter_frontend("**/*")
            if p.suffix in {".ts", ".vue"} and "weights" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [], f"前端出现 weights 读取：{offenders}")

    def test_json_files_parse(self) -> None:
        """前端配置文件必须是合法 JSON（写错一个逗号，pnpm install 直接崩）。"""
        import json

        for name in ("package.json", "tsconfig.json", "nuxt.config.ts"):
            path = FRONTEND / name
            if name.endswith(".json"):
                json.loads(path.read_text(encoding="utf-8"))

    def test_vue_sfc_structure(self) -> None:
        """SFC 骨架自检：模板/脚本标签成对，且有模板块（script 在前是合法的）。"""
        problems: list[str] = []
        for vue in iter_frontend("**/*.vue"):
            text = vue.read_text(encoding="utf-8").strip()
            rel = vue.relative_to(FRONTEND)
            if "<template" not in text:
                problems.append(f"{rel}: 缺少 <template>")
            for open_tag, close_tag in (("<template", "</template>"), ("<script", "</script>")):
                if text.count(open_tag) != text.count(close_tag):
                    problems.append(
                        f"{rel}: {open_tag} × {text.count(open_tag)} / {close_tag} × {text.count(close_tag)}"
                    )
        self.assertEqual(problems, [], f"SFC 结构异常：{problems}")

    def test_backend_imports_resolve(self) -> None:
        """编译只查语法，这里查 `from app.x.y import` 的模块是否真的存在。"""
        broken: list[str] = []
        for py in (BACKEND / "app").rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for module in re.findall(r"from (app[\w.]*) import", text):
                rel = Path(*module.split("."))
                candidates = [
                    BACKEND / rel.with_suffix(".py"),
                    BACKEND / rel / "__init__.py",
                ]
                if not any(c.exists() for c in candidates):
                    broken.append(f"{py.relative_to(BACKEND)} -> {module}")
        self.assertEqual(broken, [], f"导入了不存在的模块：{broken}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
