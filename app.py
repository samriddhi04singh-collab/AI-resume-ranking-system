from flask import Flask, render_template, request, send_file
import spacy
import PyPDF2
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import re
import os

app = Flask(__name__)

# Load spaCy NER model
nlp = spacy.load("en_core_web_sm")

# Initialize global results variable
results = []

# Extract text from PDFs
def extract_text_from_pdf(pdf_path):
    with open(pdf_path, "rb") as pdf_file:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text

# Extract name and email using spaCy NER and regex fallback
def extract_entities(text):
    # Extract emails using regex
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    
    # Use spaCy to extract candidate names
    # Candidate names are typically found in the first 1000 characters
    doc = nlp(text[:1000])
    names = []
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            clean_name = ent.text.strip().replace("\n", " ")
            # Validate name is 2-4 words and contains no numbers
            if 2 <= len(clean_name.split()) <= 4 and not any(char.isdigit() for char in clean_name):
                names.append(clean_name)
                break

    # Fallback to regex for name search near the top if spaCy misses it
    if not names:
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines[:5]:
            match = re.search(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b', line)
            if match:
                names.append(match.group(1))
                break

    return emails, names

# Extract matching keywords/skills between the JD and the resume
def extract_matching_keywords(job_description, resume_text):
    # Common technical/professional skills list
    common_skills = {
        "python", "javascript", "typescript", "react", "angular", "vue", "node.js", "express",
        "flask", "django", "fastapi", "html", "css", "sql", "nosql", "mongodb", "postgresql",
        "mysql", "oracle", "aws", "azure", "gcp", "docker", "kubernetes", "git", "github",
        "nlp", "machine learning", "deep learning", "artificial intelligence", "data science",
        "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy", "java", "c++", "c#",
        "ruby", "rails", "php", "laravel", "swift", "kotlin", "project management", "agile",
        "scrum", "product management", "ui/ux", "figma", "devops", "ci/cd", "rest api", "graphql"
    }
    
    jd_lower = job_description.lower()
    resume_lower = resume_text.lower()
    
    # Skills mentioned in the Job Description
    jd_skills = {skill for skill in common_skills if re.search(r'\b' + re.escape(skill) + r'\b', jd_lower)}
    
    # Which of those skills match in the candidate's resume
    matched = [skill for skill in jd_skills if re.search(r'\b' + re.escape(skill) + r'\b', resume_lower)]
    
    # Fallback: extract noun chunks from Job Description if no predefined skills matched
    if not jd_skills:
        doc_jd = nlp(job_description)
        jd_nouns = {token.text.lower() for token in doc_jd if token.pos_ in ["NOUN", "PROPN"] and len(token.text) > 2}
        stopwords = nlp.Defaults.stop_words
        jd_nouns = jd_nouns - stopwords
        matched = [noun for noun in jd_nouns if re.search(r'\b' + re.escape(noun) + r'\b', resume_lower)]
        matched = matched[:6]
        
    return [skill.title() for skill in matched]

@app.route('/', methods=['GET', 'POST'])
def index():
    global results
    if request.method == 'POST':
        job_description = request.form['job_description']
        resume_files = request.files.getlist('resume_files')

        # Create a directory for uploads if it doesn't exist
        if not os.path.exists("uploads"):
            os.makedirs("uploads")

        # Process uploaded resumes
        processed_resumes = []
        for resume_file in resume_files:
            if not resume_file or resume_file.filename == '':
                continue
            # Save the uploaded file
            resume_path = os.path.join("uploads", resume_file.filename)
            resume_file.save(resume_path)

            # Process the saved file
            resume_text = extract_text_from_pdf(resume_path)
            emails, names = extract_entities(resume_text)
            processed_resumes.append((names, emails, resume_text, resume_file.filename))

        # TF-IDF vectorizer
        tfidf_vectorizer = TfidfVectorizer()
        job_desc_vector = tfidf_vectorizer.fit_transform([job_description])

        # Rank resumes based on similarity
        ranked_resumes = []
        for (names, emails, resume_text, filename) in processed_resumes:
            resume_vector = tfidf_vectorizer.transform([resume_text])
            similarity = cosine_similarity(job_desc_vector, resume_vector)[0][0] * 100 
            
            name = names[0] if names else "Candidate"
            email = emails[0] if emails else "N/A"
            skills = extract_matching_keywords(job_description, resume_text)
            
            ranked_resumes.append({
                "name": name,
                "email": email,
                "similarity": round(similarity, 1),
                "skills": skills,
                "filename": filename
            })

        # Sort resumes by similarity score
        ranked_resumes.sort(key=lambda x: x["similarity"], reverse=True)

        # Assign rankings
        for idx, item in enumerate(ranked_resumes):
            item["rank"] = idx + 1

        results = ranked_resumes

    else:
        results = []

    return render_template('index.html', results=results)

@app.route('/download_csv')
def download_csv():
    global results
    # Generate the CSV content
    csv_content = "Rank,Name,Email,Similarity,Filename\n"
    for result in results:
        rank = result.get("rank", "")
        name = result.get("name", "N/A")
        email = result.get("email", "N/A")
        similarity = result.get("similarity", 0)
        filename = result.get("filename", "")
        csv_content += f'"{rank}","{name}","{email}","{similarity}%","{filename}"\n'

    # Create a temporary file to store the CSV content
    csv_filename = "ranked_resumes.csv"
    with open(csv_filename, "w", encoding="utf-8") as csv_file:
        csv_file.write(csv_content)

    csv_full_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), csv_filename)
    return send_file(csv_full_path, as_attachment=True, download_name="ranked_resumes.csv")

if __name__ == '__main__':
    app.run(debug=True)
