from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/message', methods=['POST'])
def message():
    data = request.get_json()
    user_message = data.get('message', '').lower()
    
    # simple test replies
    if "book" in user_message:
        response = "Sure! What day and time would you like to book your call?"
    else:
        response = "Hi! I can help you book your assessment. Try typing: 'I want to book a call'"
    
    return jsonify({"response": response})

if __name__ == "__main__":
    app.run(debug=True)