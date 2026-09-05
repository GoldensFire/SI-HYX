# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# tools/export_dyhit_onnx.py — превращает веса DyHiT (.pth.tar от авторов
# статьи) в models/dyhit.onnx, который умеет читать dyhit_tracker.py
# («Монтаж → Привязать к объекту»). Этим скриптом сделан лежащий в models/ файл.
#
# Зачем отдельный скрипт: в самой программе PyTorch НЕТ (он намеренно исключён
# из сборки, см. SI-HYX.spec) — трекер работает только на onnxruntime. Конвертация
# разовая и делается ВНЕ приложения, во временном окружении.
#
# Что экспортируем: быструю ветку DyHiT (route 1) — patch_embed → блоки первой
# стадии → bottleneck_small → box_head_small, плюс карту роутера. Именно этот
# режим в experiments/DyHiT/stage2.yaml помечен как THRESHOLD: -9999
# («only use route1») и даёт заявленные авторами ~299 FPS против 175 у HiT-Base.
#
# Подготовка (один раз, в ОТДЕЛЬНОМ окружении — не в основном, чтобы не тащить
# torch/timm в проект):
#
#   git clone https://github.com/kangben258/HIT.git
#   python -m venv hitenv
#   hitenv\Scripts\python -m pip install torch timm easydict pyyaml onnx onnxruntime
#   hitenv\Scripts\python tools\export_dyhit_onnx.py ^
#       --repo HIT --checkpoint DyHiT_ep0060.pth.tar --output models\dyhit.onnx
#
# Веса лежат в Google Drive репозитория HIT (папка checkpoints), см. его README.
# Файл чекпоинта — pickle: грузите только те, что скачали у авторов сами.
#
# Готовый граф: search [1,3,256,256] + template [1,3,128,128] (RGB, /255,
# ImageNet-норма) → outputs_coord_new [1,1,4] (cx,cy,w,h в долях поисковой
# области) + router_score [1,256,1].

import argparse
import os
import sys
import types

import numpy as np
import torch
from torch import nn


def _patch_torch_for_cpu_export():
    """Репозиторий HIT рассчитан на GPU и зовёт .cuda() прямо в конструкторах
    (head.py), а torch 2.6+ грузит чекпоинты с weights_only=True, хотя в них
    лежит и объект статистики тренировки. Для разового экспорта на CPU обе
    привычки обезвреживаем."""
    torch.Tensor.cuda = lambda self, *a, **k: self
    nn.Module.cuda = lambda self, *a, **k: self

    orig_load = torch.load

    def _load(*a, **kw):
        kw.setdefault("weights_only", False)
        return orig_load(*a, **kw)

    torch.load = _load

    # Анпиклер чекпоинта тянет lib.train → tensorboardX, которого в окружении нет.
    tb = types.ModuleType("tensorboardX")
    tb.SummaryWriter = object
    sys.modules.setdefault("tensorboardX", tb)


class DyHiTRoute1(nn.Module):
    """Инференс-граф быстрой ветки DyHiT — то же, что делает lib/models/HiT/
    hit.py::DyHiT.forward при score > threshold, только без ветвлений (в ONNX
    они не нужны: тяжёлой ветки в графе нет)."""

    def __init__(self, dy, box_xyxy_to_cxcywh):
        super().__init__()
        body = dy.model1.backbone.body
        self._to_cxcywh = box_xyxy_to_cxcywh
        self.patch_embed = body.patch_embed
        self.blocks1 = body.blocks[0:body.fb_idx[0]]   # блоки до первого Subsample
        self.router = body.router
        self.bottleneck_small = dy.bottleneck_small
        self.box_head_small = dy.box_head_small
        self.num_patch_x = dy.num_patch_x              # 256 токенов поисковой области
        self.feat_len_s = dy.feat_len_s
        self.feat_sz_s = dy.feat_sz_s

    def forward(self, search, template):
        # Порядок как в трекере авторов: images_list = [search, template].
        xs = self.patch_embed(search).flatten(2).transpose(1, 2)
        xt = self.patch_embed(template).flatten(2).transpose(1, 2)
        xz1 = self.blocks1(torch.cat((xs, xt), dim=1))
        score = self.router(xz1[:, :self.num_patch_x, :]).sigmoid()

        cls = xz1.mean(1).unsqueeze(1)
        xz_mem = self.bottleneck_small(torch.cat((cls, xz1), dim=1).permute(1, 0, 2))
        output_embed = xz_mem[0:1, :, :].unsqueeze(-2)
        x_mem = xz_mem[1:1 + self.num_patch_x]

        enc_opt = x_mem[-self.feat_len_s:].transpose(0, 1)
        dec_opt = output_embed.squeeze(0).transpose(1, 2)
        att = torch.matmul(enc_opt, dec_opt)
        opt = (enc_opt.unsqueeze(-1) * att.unsqueeze(-2)).permute((0, 3, 2, 1)).contiguous()
        bs, nq, ch, _hw = opt.size()
        opt_feat = opt.view(-1, ch, self.feat_sz_s, self.feat_sz_s)
        coord = self._to_cxcywh(self.box_head_small(opt_feat)).view(bs, nq, 4)
        return coord, score


def main():
    ap = argparse.ArgumentParser(description="DyHiT .pth.tar → models/dyhit.onnx")
    ap.add_argument("--repo", required=True, help="папка клона github.com/kangben258/HIT")
    ap.add_argument("--checkpoint", required=True, help="веса DyHiT (stage2), .pth.tar")
    ap.add_argument("--output", default=os.path.join("models", "dyhit.onnx"))
    ap.add_argument("--opset", type=int, default=14)
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    ckpt = os.path.abspath(args.checkpoint)
    out = os.path.abspath(args.output)
    if not os.path.isdir(os.path.join(repo, "lib")):
        raise SystemExit(f"В {repo} не видно репозитория HIT (нет папки lib)")

    _patch_torch_for_cpu_export()
    sys.path.insert(0, repo)
    os.chdir(repo)          # конфиги репозитория ищутся относительно его корня

    from lib.config.DyHiT.config import cfg, update_config_from_file
    from lib.models.HiT import build_dyhit
    from lib.utils.box_ops import box_xyxy_to_cxcywh
    import lib.models.HiT.levit_utils as levit_utils

    update_config_from_file(os.path.join(repo, "experiments", "DyHiT", "stage2.yaml"))
    cfg.TRAIN.STAGE = 2
    cfg.TRAIN.WEIGHT = ckpt          # отсюда build_dyhit возьмёт веса

    print("собираю модель…")
    model = build_dyhit(cfg)
    levit_utils.replace_batchnorm(model.model1.backbone.body)   # слияние conv+bn
    model.eval()

    net = DyHiTRoute1(model, box_xyxy_to_cxcywh).eval()
    search = torch.randn(1, 3, cfg.TEST.SEARCH_SIZE, cfg.TEST.SEARCH_SIZE)
    template = torch.randn(1, 3, cfg.TEST.TEMPLATE_SIZE, cfg.TEST.TEMPLATE_SIZE)
    with torch.no_grad():
        coord, score = net(search, template)
    print("torch:", list(coord.shape), "score:", list(score.shape))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    print("экспорт в ONNX…")
    torch.onnx.export(
        net, (search, template), out,
        export_params=True, opset_version=args.opset, do_constant_folding=True,
        input_names=["search", "template"],
        output_names=["outputs_coord_new", "router_score"],
        dynamo=False,
    )

    import onnxruntime as ort
    sess = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
    ort_out = sess.run(None, {"search": search.numpy(), "template": template.numpy()})
    np.testing.assert_allclose(coord.numpy(), ort_out[0], rtol=1e-3, atol=1e-5)
    print(f"готово: {out} ({os.path.getsize(out) // 1024 // 1024} МБ), "
          f"вывод совпадает с torch")


if __name__ == "__main__":
    main()
