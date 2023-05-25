# 02 Maplotlibグラフ画像からHTMLイメージタグを生成する方法

> (参考URL) 本家サイト  
<https://matplotlib.org/3.5.0/gallery/user_interfaces/web_application_server_sgskip.html>  
**Embedding in a web application server (Flask)**

> 以下は上記サイトのサンプルコード  
一番の肝は、画像イメージをHTMLのイメージタグを生成する処理です。  
※(1)から(4)までのコード部分

```python
import base64
from io import BytesIO

from flask import Flask
from matplotlib.figure import Figure

app = Flask(__name__)

@app.route("/")
def hello():
    # Generate the figure **without using pyplot**.
    fig = Figure() 
    ax = fig.subplots()
    ax.plot([1, 2])
    # Save it to a temporary buffer.
    buf = BytesIO()                                           (1)
    fig.savefig(buf, format="png")                            (2)
    # Embed the result in the html output.
    data = base64.b64encode(buf.getbuffer()).decode("ascii")  (3)
    return f"<img src='data:image/png;base64,{data}'/>"       (4)
```