import pytest

from clr.private_auth_benchmark import recommend_global_login_ceiling


def test_recommended_login_ceiling_uses_total_host_cpu_budget():
    assert recommend_global_login_ceiling(
        median_hash_seconds=0.5,
        vcpus=2,
        target_cpu_share=0.10,
    ) == 24


@pytest.mark.parametrize(
    "kwargs",
    [
        {"median_hash_seconds": 0, "vcpus": 2, "target_cpu_share": 0.10},
        {"median_hash_seconds": 0.5, "vcpus": 0, "target_cpu_share": 0.10},
        {"median_hash_seconds": 0.5, "vcpus": 2, "target_cpu_share": 0},
        {"median_hash_seconds": 0.5, "vcpus": 2, "target_cpu_share": 1.1},
    ],
)
def test_recommended_login_ceiling_rejects_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        recommend_global_login_ceiling(**kwargs)
