"""Windows-friendly bootstrap and interactive runner. Python 3.10+ required."""
import argparse
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import venv


ROOT = Path(__file__).resolve().parent


def positive_number(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a positive finite number')
    return value


def prompt_dimension(name, default):
    while True:
        answer = input(f'{name} in mm [Enter = {default:g}]: ').strip()
        try:
            return positive_number(answer or default, name)
        except ValueError as error:
            print(error)


def prompt_layers(default):
    while True:
        answer = input(f'Number of copper layers [Enter = {default}]: ').strip()
        try:
            layers = int(answer or str(default))
            if layers < 2 or layers > 32 or layers % 2:
                raise ValueError
            return layers
        except ValueError:
            print('Enter an even number of layers from 2 to 32 (for example, 4 or 6).')


def ensure_environment():
    """Install only into this package's environment; leave other Pythons alone."""
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required. Run launch.py with your newer interpreter.')
    env_dir = ROOT / '.venv'
    env_python = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if Path(sys.prefix).resolve() != env_dir.resolve():
        if not env_python.is_file():
            print('First run: creating a local Python environment...', flush=True)
            venv.EnvBuilder(with_pip=True).create(env_dir)
        clean_env = os.environ.copy()
        clean_env.pop('PYTHONPATH', None)
        clean_env.pop('PYTHONHOME', None)
        return subprocess.call([str(env_python), str(Path(__file__).resolve()), *sys.argv[1:]],
                               cwd=ROOT, env=clean_env)
    try:
        importlib.import_module('networkx')
        importlib.import_module('PIL.Image')
        shapely = importlib.import_module('shapely')
        if not hasattr(shapely, 'make_valid') or int(shapely.__version__.split('.')[0]) < 2:
            raise ImportError('Shapely 2 or newer is required')
    except ImportError:
        print('First run: installing the three required packages (Internet needed)...', flush=True)
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:',
                               '--disable-pip-version-check', '-r', str(ROOT/'requirements.txt')])
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--non-interactive', action='store_true', help='Use settings.json without prompts')
    args = parser.parse_args()
    settings = json.loads((ROOT/'settings.json').read_text(encoding='utf-8'))
    settings['width_mm'] = positive_number(settings['width_mm'], 'Width')
    settings['height_mm'] = positive_number(settings['height_mm'], 'Height')
    status = ensure_environment()
    if status is not None:
        return status
    print('PCB reconstruction from X-ray annotation layers', flush=True)
    print('Inputs: ' + str(ROOT/'inputs'), flush=True)
    if not args.non_interactive:
        print('Enter the physical width and length represented by your images.')
        settings['width_mm'] = prompt_dimension('Board width', settings['width_mm'])
        settings['height_mm'] = prompt_dimension('Board length (height)', settings['height_mm'])
        settings['layers'] = prompt_layers(settings['layers'])
    print(f'Using {settings["width_mm"]:g} x {settings["height_mm"]:g} mm, '
          f'{settings["layers"]} layers.',flush=True)
    import kicad_reconstruct_reviewed as reconstruction
    reconstruction.run(SimpleNamespace(input_dir=ROOT/'inputs', output_dir=ROOT/'output', **settings))
    print('\nFinished. Open output/reviewed_tracks.kicad_pcb in KiCad.')
    print('The coordinate netlist is output/reviewed_netlist.txt.')
    print('Image-only copper planes remain unresolved; see output/review_report.json.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'\nCould not complete reconstruction: {error}', file=sys.stderr)
        if isinstance(error,subprocess.CalledProcessError):
            print('Dependency setup failed. Check the installation error above and your Internet connection.', file=sys.stderr)
        else:
            print('See the reconstruction error above; no dependency reinstall is needed for geometry errors.', file=sys.stderr)
        raise SystemExit(1)
