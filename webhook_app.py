from quart import Quart, Response

app = Quart(__name__)

@app.route('/Fk2yp7PVH20', methods=['POST'])
async def ipn():
    return Response(status=204)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
