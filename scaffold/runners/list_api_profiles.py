from __future__ import annotations

from scaffold.local import local_api_config as config


def main():
    print("profiles:")
    for name, profile in sorted(config.API_PROFILES.items()):
        has_key = "yes" if profile.get("api_key") else "NO"
        print(
            f"  {name:<22} model={profile.get('model_name')!r:<28} "
            f"base={profile.get('base_url')!r} key={has_key}"
        )
    print()
    print("roles:")
    for role, value in sorted(config.API_ROLES.items()):
        print(f"  {role:<22} -> {value!r}")


if __name__ == "__main__":
    raise SystemExit(main())
