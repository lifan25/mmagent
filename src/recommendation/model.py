"""Normal upstream import, with documented runtime-only fixes."""

import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "third_party/SSPNet/src"))
from modules import SSPNetModel


class SSPNetAdapter(SSPNetModel):
    def __init__(self, config, sizes, ehr, ddi, device):
        super().__init__(emb_dim=config["dim"], voc_size=sizes, ehr_adj=ehr,
                         ddi_adj=torch.as_tensor(ddi), device=device)
        # Upstream FloatTensor(1) leaves these trainable scalars uninitialized.
        with torch.no_grad():
            self.inter.fill_(config["initial_inter"])
            self.garm.fill_(config["initial_garm"])
        self.register_buffer("ddi_tensor", torch.as_tensor(ddi, dtype=torch.float32))
        self.register_buffer("med_ids", torch.arange(sizes[2]))
        self.to(device)

    def visual(self, *args):
        # Original debug plots consume answer labels and write a hardcoded home path.
        return None

    def forward(self, patient):
        # ddi_mask_H is an unused legacy argument; no invented molecular mask is needed.
        return super().forward(self.med_ids, patient, None, self.ddi_tensor)
