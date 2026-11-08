"""Deterministic local experiment processing; no instrument or network access."""
from dataclasses import asdict, dataclass
import math
import random
import re


def quantity(value, unit, prefixes, low, high):
    if isinstance(value, bool):
        raise ValueError("参数必须为数值，不能为布尔值")
    if isinstance(value, str):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kM]?)" + re.escape(unit) + r"\s*", value)
        if not m or m[2] not in prefixes:
            raise ValueError(f"单位应为 {unit}，可用前缀 {prefixes}")
        value = float(m[1]) * {"": 1, "k": 1000, "M": 1000000}[m[2]]
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"参数范围应为 {low}–{high} {unit}")
    return float(value)


@dataclass(frozen=True)
class Config:
    frequency: float = 100
    sample_rate: float = 100000
    samples: int = 20000
    voltage: float = 3.3
    outputs: tuple = (0, 1)
    input: int = 2

    @classmethod
    def parse(cls, values):
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise ValueError("包含未知实验参数")
        c = cls()
        frequency = quantity(values.get("frequency", c.frequency), "Hz", ("",), 1, 1000)
        rate = quantity(values.get("sample_rate", c.sample_rate), "S/s", ("", "k", "M"), 1000, 1000000)
        samples = values.get("samples", c.samples)
        if type(samples) is not int or not 4 <= samples <= 200000:
            raise ValueError("采样点数必须为 4–200000 的整数")
        if rate < frequency * 20 or samples / rate > 5:
            raise ValueError("每个码元至少 20 点，记录时长最多 5 秒")
        if type(values.get("voltage", 3.3)) not in (int, float) or values.get("voltage", 3.3) != 3.3:
            raise ValueError("CD4007UBE 本流程固定为 3.3 V；不能沿用 5 V")
        outputs = values.get("outputs", [0, 1])
        if not isinstance(outputs, (list, tuple)) or any(type(x) is not int for x in outputs) or tuple(outputs) != (0, 1):
            raise ValueError("只允许 DIO0/1 输出，DIO2 不得输出")
        if type(values.get("input", 2)) is not int or values.get("input", 2) != 2:
            raise ValueError("Y 只接 DIO2 输入；不得与输出端口冲突")
        return cls(frequency, rate, samples)

    def json(self):
        result = asdict(self)
        result["outputs"] = list(self.outputs)
        return result


@dataclass
class Capture:
    config: Config
    a: list
    b: list
    y: list
    source: str = "simulated"


def simulate(config, seed=17, fault="none", cancelled=lambda: False):
    if fault not in ("none", "stuck_low", "nand") or type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("未知模拟故障或随机种子")
    rng = random.Random(seed)
    a, b, y = [], [], []
    last = -1
    av = bv = 0
    for i in range(config.samples):
        if i % 512 == 0 and cancelled():
            raise InterruptedError("本地任务已停止")
        symbol = int(i * config.frequency / config.sample_rate)
        if symbol != last:
            av, bv = rng.randrange(2), rng.randrange(2)
            last = symbol
        a.append(av)
        b.append(bv)
        y.append(0 if fault == "stuck_low" else (1 - (av & bv) if fault == "nand" else av & bv))
    return Capture(config, a, b, y)


def analyze(data, guard=2):
    n = data.config.samples
    if data.source not in ("simulated", "hardware", "imported_unverified"):
        raise ValueError("未知数据来源")
    if any(len(x) != n for x in (data.a, data.b, data.y)):
        raise ValueError("通道长度或采样点数不一致")
    if any(type(v) is not int or v not in (0, 1) for ch in (data.a, data.b, data.y) for v in ch):
        raise ValueError("逻辑值必须为 0 或 1")
    if type(guard) is not int or not 0 <= guard <= 10:
        raise ValueError("边沿排除范围应为 0–10 点")
    excluded = set()
    for i in range(1, n):
        if data.a[i] != data.a[i-1] or data.b[i] != data.b[i-1]:
            excluded.update(range(max(0, i-guard), min(n, i+guard+1)))
    rows = [{"a": a, "b": b, "expected": a & b, "count": 0, "errors": 0} for a, b in ((0,0),(0,1),(1,0),(1,1))]
    errors = []
    for i, (a, b, y) in enumerate(zip(data.a, data.b, data.y)):
        if i in excluded:
            continue
        row = rows[a*2+b]
        row["count"] += 1
        if y != a & b:
            row["errors"] += 1
            if len(errors) < 20:
                errors.append(i)
    coverage = sum(row["count"] > 0 for row in rows)
    error_count = sum(row["errors"] for row in rows)
    verdict = "FAIL" if error_count else ("PASS" if coverage == 4 else "INCOMPLETE")
    return {"source": data.source, "verdict": verdict, "coverage": coverage,
            "errors": error_count, "samples": n, "stable_samples": n-len(excluded),
            "excluded_edges": len(excluded), "guard_samples": guard,
            "duration_s": n/data.config.sample_rate, "rows": rows, "first_error_indices": errors,
            "scope": "仅对采样记录中稳态与逻辑及四种输入覆盖判读；不评估电气连通、模拟电压、毛刺或传播延迟"}


GUIDE = [
    {"title": "断电准备", "text": "先关闭 V+、V− 和所有数字/波形输出。核对芯片为 CD4007UBE，缺口朝上。照片只能帮助辨认，不能证明连通。"},
    {"title": "电源与地", "text": "V+ 设 3.3 V 并保持关闭。14、2、11 脚同接 V+；7、9 脚接 GND。104 电容跨接 14 脚附近电源与 7 脚附近地。V− 保持关闭。"},
    {"title": "前级与反相器", "text": "1、5、13、10 脚合并为中间节点 N；4 与 8 脚相连且不直连电源或地。DIO0 → 3 脚 A；DIO1 → 6 脚 B。12 脚为最终 Y。"},
    {"title": "测量端与静态核对", "text": "DIO2 仅输入，接 12 脚 Y；CH2+ 接 Y，CH2− 接 GND。确认初始 A=B=0、端口无争用。实际供电须另行确认接线，MVP 不执行。静态 00/01/10 → 0，11 → 1。"},
    {"title": "动态采样", "text": "手册目标：停止 Digital I/O 后，用 Pattern Generator 的 DIO0/1 各设 Random 100 Hz；Logic Analyzer 采 DIO0/1/2，100 kS/s、20000 点、Delay 0、Auto、Single。本原型在模拟器中设置并回读这些参数。"},
    {"title": "判读与保存", "text": "本地排除输入边沿附近各 2 点，逐点检查 Y=A&B，并统计四种输入覆盖。缺少状态时结论为覆盖不足。保存 CSV、判读 JSON 和哈希清单；模拟通过不能作为硬件实验结论。"},
]
