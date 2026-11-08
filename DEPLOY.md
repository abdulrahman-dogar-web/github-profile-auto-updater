# Deploying / hosting

This project is a script, not a website, so there is no site to host.

- **Run it locally:** `pip install -r requirements.txt && python3 update_profile.py`
- **Run it automatically:** the included `.github/workflows/update-profile.yml`
  runs weekly (Mondays 00:00 UTC) and on push, and commits the regenerated
  `PROFILE_README.md` back to this repo — that is its "live" output.
- **Use the output:** copy the generated `PROFILE_README.md` into the
  `README.md` of the `abdulrahman-dogar-web` profile repo to make it your
  live GitHub profile.
