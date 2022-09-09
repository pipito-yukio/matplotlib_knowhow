# Matplotlib & Pandas know-how

【実行環境】Ubuntu 18.04

```bash
$ lsb_release -a
No LSB modules are available.
Distributor ID:	Ubuntu
Description:	Ubuntu 18.04.6 LTS
Release:	18.04
Codename:	bionic
```

## python仮想環境の作成

* ホームにサブディレクトリ py_venv を作成し、その中に Python仮想環境名 **py_matplotlib** を作成  
python3 **-m venv** py_matplotlib

```bash
$ mkdir py_venv
$ cd py_venv
~/py_venv$ python3 -m venv py_matplotlib
```

* **sourceコマンド**で仮想環境 py_matplotlib に入り pip 自体をアップデート
```
~/py_venv$ source py_matplotlib/bin/activate
(py_matplotlib) ~/py_venv$ pip install -U pip
```

* **Matplotlib** ライブラリと **Pandas** ライブラリをインストール
```bash
(py_matplotlib) ~/py_venv$ pip install matplotlib pandas
```

[01 Matplotlibに日本語フォントを表示する](01_useCjkFont/README.md#01-matplotlibに日本語フォントを表示する)

