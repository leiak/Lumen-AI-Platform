# Storage Abstraction (M38.1, 2026-08-26)

> 本文档解释 **为什么** 有 storage 抽象层、**何时** 用哪个 backend、**怎么**
> 把代码从 local 模式切到 MinIO / S3 模式(端到端 KB 上传链路)。

## 1. 架构概览

```
用户上传 → backend FastAPI
              ↓
        storage.put_object(key, bytes)
              ↓
       StorageBackend (ABC)
       ┌──────┴───────┐
       ↓              ↓
   LocalBackend   S3Backend
       ↓              ↓
   本地 ./data    MinIO / AWS / Aliyun OSS / Tencent COS
```

**单一入口** `lumen_services.storage.get_storage_backend()` 返回进程内 singleton,
由 `STORAGE_BACKEND` env var 决定 backend 类型。所有 KB / image / stock / video /
music 服务的文件 I/O 都过这一层(替换掉原本散落的 `open(file_path)`)。

## 2. 选型决策表

| 场景 | 推荐 backend | 理由 |
|------|-------------|------|
| 本机 dev / 单租户 demo | `LocalBackend` | 零依赖,文件可直接 grep 看 |
| 单租户生产 | `S3Backend` → MinIO 自托管 | 跨节点共享存储 |
| 多租户 SaaS | `S3Backend` → AWS / Aliyun OSS | 跨 region 复制 + lifecycle |
| 测试 (CI / pytest) | `LocalBackend` 或 `moto[s3]` mock | 隔离 + 无外部依赖 |

**何时** 切换:
- 单文件 < 5 MiB → single PUT(零开销)
- 单文件 ≥ 5 MiB → 自动 multipart(避免 S3 单次 PUT 5GB 上限 + 内存有界)
- 1GB+ 大文件 → multipart + 多 part 重试(follow-up,本期未覆盖)

## 3. Multipart 阈值 + 单进程上限

**阈值常量** `lumen_services/storage/s3_backend.py:25-29`:

```python
_MULTIPART_THRESHOLD_BYTES = 5 * 1024 * 1024   # 5 MiB
_DEFAULT_PART_SIZE_BYTES = 5 * 1024 * 1024     # 5 MiB / part
```

`put_object()` 看到 `len(data) >= 5 MiB` 自动走 `create_multipart_upload` →
`upload_part` × N → `complete_multipart_upload`。任何 part 失败 → `abort_multipart_upload`
清理 server-side resources(incomplete multipart 会在 MinIO 累积 storage cost 直到 expiry)。

## 4. Tenant 隔离

**约定**:storage key 路径必须按 `<tenant_id>/<kb_id>/<doc_uuid>/<filename>` 拼。
例如 `1/5/doc-a1b2c3/report.pdf`。

```python
# 写
storage.put_object(f"{tenant_id}/{kb_id}/{doc_uuid}/{filename}", data)

# 读
storage.get_object(f"{tenant_id}/{kb_id}/{doc_uuid}/{filename}")
```

**前端读受保护资源**(参考 CLAUDE.md §3 `<img>` Bearer 模式):
- Local: `GET /api/v1/storage/local/<key>` + `Authorization: Bearer <token>` →
  fetch+blob+createObjectURL(unmount 时 `URL.revokeObjectURL(prev)`)
- S3: `get_presigned_url(key, expiry=3600)` 直接拿到临时 URL(无 Bearer 头)

**list_objects prefix 隔离**:`storage.list_objects(prefix="<tenant_id>/")` 只返
该 tenant 的子目录,UI 后台管理用这个扫描。

## 5. Parsers 适配 (M38.1 follow-up)

PDF / docx / html 解析器底层依赖 `pdfplumber.open(file_path)` /
`zipfile.ZipFile(file_path)` / `docling.convert(file_path)` — 这些库**只接
filesystem path**,不接 stream。

**适配模式**:`DocumentParser.parse(file_path, storage_key=None)` 入口先调
`storage.resolve_to_local_path(storage_key)` 把 S3 对象下成临时文件,cleanup
在 `finally` 块。Local backend 上 `resolve_to_local_path` 直接返现有路径,
零拷贝。

```python
# 后端调方 (e.g. knowledge.upload_document)
DocumentParser().parse(
    file_path=None,                    # legacy,空
    storage_key=doc.asset_storage_key, # M38.1 preferred
)
```

**`storage_key` 缺失/失败 → 静默 fallback 到 `file_path`**,不影响 pre-M38.1
调用方。

## 6. 迁移路径

`/api/v1/storage/migrate-to-s3` 是 admin-only 的冷迁移 endpoint:

1. **Cold migration**(一次性):`POST /api/v1/storage/migrate-to-s3?batch_size=100`
   把 `documents.file_path` legacy 路径读出来 → 上传到 S3 → 写
   `asset_storage_key` + `storage_backend='s3'` → commit。
2. **Dual write**(过渡期):写新对象时同时写 local + S3,读优先 S3(本期未实
   现,follow-up)。
3. **S3 only**:所有 legacy `file_path` 已迁移 + 新上传不再写 local,LocalBackend
   可退役。

**rclone 集成**(follow-up):大文件 / 海量数据迁移用 rclone sync 比逐行 Python
   上传快 10×。

## 7. 测试矩阵

| 层级 | 命令 | 依赖 |
|------|------|------|
| Unit (moto mock) | `pytest tests/unit/test_storage_backends.py` | `moto[s3]` |
| Unit (parser 适配) | `pytest tests/unit/test_parsers_with_storage.py` | 无 |
| Live integration | `pytest tests/integration/test_storage_minio_live.py` | localhost:29000 MinIO |
| 压测 baseline | `python -m scripts.bench_minio --doc-size 100KB` | localhost:29000 MinIO |

## 8. 相关文档

- [M38.1 spec §10 risk](https://example.com/spec) — parsers 适配的 spec 风险段
- [dev-env.md §10 MinIO](../troubleshooting/dev-env.md#10-minio-m381-follow-up-2026-08-31) — 启
  MinIO + 切 backend + 跑压测的操作指南
- [CLAUDE.md §3 `<img>` Bearer 模式](../../CLAUDE.md#3-前端读取约定) — 前端读受保护
  资源

---

**Out of scope**(本 plan 明确未做,follow-up):
- boto3 Windows registry proxy bypass(参考 `httpx-proxy-bypass-2026-08-31.md`)
- 1GB+ 大文件(依赖 multipart retry + 网络层调优)
- `STORAGE_BACKEND` 运行时切换(工厂 singleton 限制)
- rclone 集成 `migrate-to-s3`
- Lifecycle / 版本控制 / 跨 region 复制