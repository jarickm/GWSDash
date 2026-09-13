from old.app import app

if __name__ == '__main__':
    from waitress import serve
    print("Serving OneWorkspace Adoption System on http://0.0.0.0:5000...")
    serve(app, host='0.0.0.0', port=5000)