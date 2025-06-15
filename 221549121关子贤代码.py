import os
import jieba
import hashlib
import random
import numpy as np
import requests
import json
import time
import re
import tkinter as tk
from tkinter import scrolledtext, ttk
from collections import defaultdict
from sklearn.metrics.pairwise import cosine_similarity
from datetime import datetime, timedelta
import threading
import itertools
from ttkthemes import ThemedTk

# 禁用jieba日志
import logging
logging.disable(logging.INFO)

# 添加自定义词典增强分词
custom_words = ["智能手机", "最新款", "红烧肉", "入门教程", "Python编程", "人工智能", "深度学习", "气候变化", 
               "健康饮食", "英语口语", "股票投资", "笔记本电脑", "儿童教育", "环保生活", "面试准备", 
               "新冠病毒", "电影推荐", "种植蔬菜", "汽车保养", "编程语言", "缓解压力", "世界历史", "心理健康"]
for word in custom_words:
    jieba.add_word(word)

class BilingualSearchEngine:
    def __init__(self, appid='20250530002369827', secret_key='Uq98r9bxN68g6_807jDt', cache_file='translation_cache.json'):
        """支持中英文混合搜索的离线引擎"""
        jieba.initialize()
        
        # 百度翻译API配置
        self.appid = str(appid)
        self.secret_key = str(secret_key)
        if not self.appid or not self.secret_key:
            print("警告：未配置百度翻译API，部分功能受限")
        
        # 初始化缓存
        self.cache_file = cache_file
        self.translation_cache = self._load_cache()
        self.cache_hits = 0
        self.cache_misses = 0
        
        # 本地词向量字典（增强版）
        print("正在初始化本地模型...")
        self.word_vectors = self._build_enhanced_vectors()
        self.vector_size = 100
        
        # 词形变化映射表
        self.word_forms = self._build_word_forms()
        
        # 内容存储
        self.content_data = {}
        self.content_vectors = {}
        
        # 构建词汇表用于部分匹配
        self.vocabulary = self._build_vocabulary()
        
        # 搜索记录和热点区
        self.search_history = []
        self.hot_topics = defaultdict(int)
        self.hot_expirations = {}
        
        print("模型就绪！")
        
        # 初始化示例内容
        self._init_sample_content()
        
        # 启动热点清理线程
        self._start_hot_topic_cleaner()
    
    def _start_hot_topic_cleaner(self):
        """启动热点清理线程"""
        def cleaner():
            while True:
                self._clean_expired_hot_topics()
                time.sleep(60)  # 每分钟检查一次
                
        thread = threading.Thread(target=cleaner, daemon=True)
        thread.start()
    
    def _clean_expired_hot_topics(self):
        """清理过期的热点"""
        now = datetime.now()
        expired_topics = []
        
        for topic, expiration in self.hot_expirations.items():
            if now > expiration:
                expired_topics.append(topic)
        
        for topic in expired_topics:
            del self.hot_topics[topic]
            del self.hot_expirations[topic]
    
    def add_search_history(self, query, result):
        """添加搜索历史"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.search_history.append({
            'query': query,
            'translated_query': result.get('translated_query', ''),
            'timestamp': timestamp,
            'found': len(result.get('results', [])) > 0
        })
        
        # 更新热点计数
        self.hot_topics[query] += 1
        
        # 如果达到热点阈值（5分钟5次），添加到热点区
        if self.hot_topics[query] >= 5 and query not in self.hot_expirations:
            expiration = datetime.now() + timedelta(minutes=5)
            self.hot_expirations[query] = expiration
            
    def get_search_history(self):
        """获取搜索历史"""
        return self.search_history.copy()
    
    def get_hot_topics(self):
        """获取当前热点"""
        return dict(self.hot_topics)
    
    def _build_word_forms(self):
        """构建词形变化映射表，处理program/programming等关系"""
        word_forms = {
            # 英文词形变化
            "program": ["programming", "programs", "programmed"],
            "learn": ["learning", "learns", "learned"],
            "review": ["reviews", "reviewing", "reviewed"],
            "make": ["makes", "making", "made"],
            "cook": ["cooks", "cooking", "cooked"],
            "phone": ["phones", "smartphone", "smartphones"],
            "invest": ["investment", "investing", "invested"],
            "educate": ["education", "educating", "educated"],
            "grow": ["growing", "grows", "grown"],
            "maintain": ["maintenance", "maintaining", "maintained"],
            
            # 中文词形变化（添加常见变体）
            "编程": ["编程序", "编写程序", "程序编写"],
            "学习": ["学到", "学会", "学习到"],
            "制作": ["做", "制作出", "制作成"],
            "评测": ["测评", "评价", "测试"],
            "智能手机": ["智能机", "智慧手机", "智能电话"],
            "最新款": ["最新型", "新款", "最新版本"],
            "旅游": ["旅行", "游玩", "游览"],
            "健康": ["保健", "养生", "康健"],
            "投资": ["投入", "投钱", "资本投入"],
            "教育": ["教导", "培育", "教养"],
        }
        return word_forms
    
    def _get_word_base_form(self, word):
        """获取单词的基础形式"""
        # 如果是中文，直接返回
        if not self._is_english(word):
            return word
        
        # 检查是否是已知词形的变体
        for base, forms in self.word_forms.items():
            if word in forms or word == base:
                return base
                
        return word
    
    def _build_vocabulary(self):
        """构建词汇表用于部分匹配"""
        vocab = set()
        for data in self.content_data.values():
            # 添加英文单词
            for word in data['english'].split():
                vocab.add(word.lower())
            # 添加中文词语
            for word in jieba.lcut(data['chinese']):
                vocab.add(word)
        return vocab
    
    def _load_cache(self):
        """加载翻译缓存"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载缓存失败: {e}")
        return {}
    
    def _save_cache(self):
        """保存翻译缓存"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.translation_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存缓存失败: {e}")
    
    def _baidu_translate(self, query, from_lang='auto', to_lang='en'):
        """调用百度翻译API进行翻译（带缓存）"""
        if not query:
            return query
        
        # 生成缓存键
        cache_key = f"{from_lang}_{to_lang}_{query}"
        
        # 检查缓存
        if cache_key in self.translation_cache:
            self.cache_hits += 1
            return self.translation_cache[cache_key]
            
        self.cache_misses += 1
        
        # 无API配置时返回原文本
        if not self.appid or not self.secret_key:
            self.translation_cache[cache_key] = query
            return query
            
        url = 'https://fanyi-api.baidu.com/api/trans/vip/translate'
        salt = random.randint(32768, 65536)
        sign_str = self.appid + query + str(salt) + self.secret_key
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()
        
        params = {
            'q': query,
            'from': from_lang,
            'to': to_lang,
            'appid': self.appid,
            'salt': str(salt),
            'sign': sign
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            result = response.json()
            if 'trans_result' in result:
                translated = result['trans_result'][0]['dst']
                self.translation_cache[cache_key] = translated
                return translated
            return query
        except Exception as e:
            print(f"翻译失败: {e}")
            self.translation_cache[cache_key] = query
            return query
    
    def _build_enhanced_vectors(self):
        """构建增强版词向量（解决部分匹配问题）"""
        vectors = {
            # 中文
            "红烧肉": np.random.rand(100),
            "制作": np.random.rand(100),
            "编程": np.random.rand(100),
            "手机": np.random.rand(100),
            "评测": np.random.rand(100),
            "学习": np.random.rand(100),
            "如何": np.random.rand(100),
            "美味": np.random.rand(100),
            "家常": np.random.rand(100),
            "智能": np.random.rand(100),
            "家": np.random.rand(100),  # 添加单字词向量
            "常": np.random.rand(100),  # 添加"常"字向量
            "入门": np.random.rand(100),
            "教程": np.random.rand(100),
            "最新款": np.random.rand(100),
            "做法": np.random.rand(100),
            "最佳": np.random.rand(100),
            "方法": np.random.rand(100),
            "的": np.random.rand(100),  # 常见助词
            "智能手机": np.random.rand(100),
            "人工智能": np.random.rand(100),
            "深度学习": np.random.rand(100),
            "旅游": np.random.rand(100),
            "攻略": np.random.rand(100),
            "健康": np.random.rand(100),
            "饮食": np.random.rand(100),
            "重要": np.random.rand(100),
            "性": np.random.rand(100),
            "提高": np.random.rand(100),
            "英语": np.random.rand(100),
            "口语": np.random.rand(100),
            "全球": np.random.rand(100),
            "气候": np.random.rand(100),
            "变化": np.random.rand(100),
            "原因": np.random.rand(100),
            "瑜伽": np.random.rand(100),
            "股票": np.random.rand(100),
            "投资": np.random.rand(100),
            "基础": np.random.rand(100),
            "知识": np.random.rand(100),
            "选择": np.random.rand(100),
            "电脑": np.random.rand(100),
            "儿童": np.random.rand(100),
            "教育": np.random.rand(100),
            "环保": np.random.rand(100),
            "生活": np.random.rand(100),
            "小贴士": np.random.rand(100),
            "准备": np.random.rand(100),
            "面试": np.random.rand(100),
            "新冠": np.random.rand(100),
            "病毒": np.random.rand(100),
            "预防": np.random.rand(100),
            "措施": np.random.rand(100),
            "电影": np.random.rand(100),
            "推荐": np.random.rand(100),
            "种植": np.random.rand(100),
            "蔬菜": np.random.rand(100),
            "汽车": np.random.rand(100),
            "保养": np.random.rand(100),
            "技巧": np.random.rand(100),
            "语言": np.random.rand(100),
            "排行": np.random.rand(100),
            "榜": np.random.rand(100),
            "缓解": np.random.rand(100),
            "压力": np.random.rand(100),
            "世界": np.random.rand(100),
            "历史": np.random.rand(100),
            "大事件": np.random.rand(100),
            "音乐": np.random.rand(100),
            "心理": np.random.rand(100),
            "影响": np.random.rand(100),
            
            # 英文
            "Python": np.random.rand(100),
            "how": np.random.rand(100),
            "to": np.random.rand(100),
            "make": np.random.rand(100),
            "delicious": np.random.rand(100),
            "braised": np.random.rand(100),
            "pork": np.random.rand(100),
            "programming": np.random.rand(100),  # 确保有programming
            "tutorial": np.random.rand(100),
            "latest": np.random.rand(100),
            "smartphone": np.random.rand(100),
            "review": np.random.rand(100),
            "home-style": np.random.rand(100),
            "recipe": np.random.rand(100),
            "best": np.random.rand(100),
            "way": np.random.rand(100),
            "learn": np.random.rand(100),
            "smart": np.random.rand(100),
            "phone": np.random.rand(100),
            "style": np.random.rand(100),
            "home": np.random.rand(100),
            "program": np.random.rand(100),  # 确保有program
            "artificial": np.random.rand(100),
            "intelligence": np.random.rand(100),
            "deep": np.random.rand(100),
            "learning": np.random.rand(100),
            "travel": np.random.rand(100),
            "guide": np.random.rand(100),
            "healthy": np.random.rand(100),
            "diet": np.random.rand(100),
            "importance": np.random.rand(100),
            "improve": np.random.rand(100),
            "English": np.random.rand(100),
            "speaking": np.random.rand(100),
            "global": np.random.rand(100),
            "climate": np.random.rand(100),
            "change": np.random.rand(100),
            "reason": np.random.rand(100),
            "yoga": np.random.rand(100),
            "beginner": np.random.rand(100),
            "stock": np.random.rand(100),
            "investment": np.random.rand(100),
            "basic": np.random.rand(100),
            "knowledge": np.random.rand(100),
            "choose": np.random.rand(100),
            "laptop": np.random.rand(100),
            "child": np.random.rand(100),
            "education": np.random.rand(100),
            "method": np.random.rand(100),
            "eco-friendly": np.random.rand(100),
            "living": np.random.rand(100),
            "tips": np.random.rand(100),
            "prepare": np.random.rand(100),
            "interview": np.random.rand(100),
            "COVID-19": np.random.rand(100),
            "prevention": np.random.rand(100),
            "measures": np.random.rand(100),
            "movie": np.random.rand(100),
            "recommendation": np.random.rand(100),
            "grow": np.random.rand(100),
            "vegetables": np.random.rand(100),
            "car": np.random.rand(100),
            "maintenance": np.random.rand(100),
            "tips": np.random.rand(100),
            "language": np.random.rand(100),
            "ranking": np.random.rand(100),
            "relieve": np.random.rand(100),
            "stress": np.random.rand(100),
            "world": np.random.rand(100),
            "history": np.random.rand(100),
            "event": np.random.rand(100),
            "music": np.random.rand(100),
            "mental": np.random.rand(100),
            "health": np.random.rand(100),
            "effect": np.random.rand(100),
        }
        
        # 处理词形变化关系
        vectors["programming"] = (vectors["program"] + vectors["ing"]) if "ing" in vectors else vectors["program"]
        
        return vectors
    
    def _text_to_vector(self, text):
        """改进的文本转向量方法"""
        # 中英文分词处理
        words = []
        for word in jieba.lcut(text):
            if word.strip() and len(word) > 1:  # 过滤掉单字词（除了重要单字）
                words.append(word)
        
        # 处理英文短语
        if any(ord(c) < 128 for c in text):
            words.extend(text.lower().split())
        
        # 获取基础形式
        base_words = [self._get_word_base_form(word) for word in words]
        
        valid_vectors = []
        for word in base_words:
            if word in self.word_vectors:
                valid_vectors.append(self.word_vectors[word])
            # 如果单词是词形变化表中的基础形式，添加所有相关词向量
            elif word in self.word_forms:
                for form in self.word_forms[word]:
                    if form in self.word_vectors:
                        valid_vectors.append(self.word_vectors[form])
        
        if valid_vectors:
            return np.mean(valid_vectors, axis=0)
        return np.zeros(self.vector_size)
    
    def _init_sample_content(self):
        """初始化示例内容，通过百度翻译API获取英文翻译"""
        sample_contents = [
            (1, "如何制作美味的红烧肉"),
            (2, "Python编程入门教程"),
            (3, "最新款智能手机评测"),
            (4, "家常红烧肉的做法"),
            (5, "学习Python的最佳方法"),
            (6, "什么是人工智能"),
            (7, "如何学习深度学习"),
            (8, "北京旅游攻略"),
            (9, "健康饮食的重要性"),
            (10, "如何提高英语口语"),
            (11, "全球气候变化的原因"),
            (12, "瑜伽入门指南"),
            (13, "股票投资基础知识"),
            (14, "如何选择笔记本电脑"),
            (15, "儿童教育方法"),
            (16, "环保生活小贴士"),
            (17, "如何准备面试"),
            (18, "新冠病毒预防措施"),
            (19, "2023年热门电影推荐"),
            (20, "如何在家种植蔬菜"),
            (21, "汽车保养技巧大全"),
            (22, "编程语言排行榜"),
            (23, "如何缓解工作压力"),
            (24, "世界历史大事件"),
            (25, "音乐对心理健康的影响"),
        ]
        
        for content_id, chinese_text in sample_contents:
            # 通过百度翻译API获取英文翻译
            english_text = self._baidu_translate(chinese_text, 'zh', 'en')
            self.index_content(content_id, chinese_text, english_text)
            # 添加延迟避免API限流
            time.sleep(0.1)
    
    def index_content(self, content_id, chinese_text, english_text=None):
        """索引内容"""
        if english_text is None:
            english_text = self._baidu_translate(chinese_text, 'zh', 'en')
        combined_text = f"{chinese_text} {english_text}"
        self.content_data[content_id] = {
            'chinese': chinese_text,
            'english': english_text,
            'combined': combined_text
        }
        self.content_vectors[content_id] = {
            'vector': self._text_to_vector(combined_text),
            'text': combined_text
        }
        # 新增：分词和子集索引
        chinese_words = list(jieba.lcut(chinese_text))
        english_words = english_text.split()
        chinese_subs = set()
        for w in chinese_words:
            chinese_subs |= self._get_all_substrings(w)
        english_subs = set()
        for w in english_words:
            english_subs |= self._get_all_letter_combinations(w.lower())
        self.content_data[content_id].update({
            'chinese_words': chinese_words,
            'english_words': [w.lower() for w in english_words],
            'chinese_subs': chinese_subs,
            'english_subs': english_subs,
        })
    
    def _get_all_substrings(self, word):
        # 获取所有长度>=1的子串
        return set(word[i:j] for i in range(len(word)) for j in range(i+1, len(word)+1))
    
    def _get_all_letter_combinations(self, word):
        # 获取所有长度>=1的乱序字母组合（大小写不敏感）
        word = word.lower()
        combs = set()
        for l in range(1, len(word)+1):
            for c in itertools.combinations(word, l):
                combs.add(''.join(c))
        return combs
    
    def _substring_priority(self, query, content, from_lang):
        # 顺序子串优先（连续）> 乱序子集
        query = query.strip().lower()
        query_words = list(jieba.lcut(query))
        query_en = query.split()
        # 中文顺序子串
        chinese_text = content['chinese']
        chinese_priority = 0
        for qw in query_words:
            if qw in chinese_text:
                chinese_priority += 2  # 顺序子串优先
            elif any(sub in content['chinese_subs'] for sub in self._get_all_substrings(qw)):
                chinese_priority += 1  # 乱序子集
        # 英文顺序子串
        english_text = content['english'].lower()
        english_priority = 0
        for qw in query_en:
            if qw in english_text:
                english_priority += 2
            elif any(sub in content['english_subs'] for sub in self._get_all_letter_combinations(qw)):
                english_priority += 1
        return chinese_priority + english_priority

    def _p_letter_priority(self, query, content):
        # 只处理英文单字母（如p）
        q = query.strip().lower()
        if len(q) != 1 or not q.isalpha():
            return 0
        # 原文英文首字母
        english_words = content.get('english_words', [])
        if english_words and english_words[0] and english_words[0][0] == q:
            return 4
        # 原文英文其他位置
        for ew in english_words[1:]:
            if ew and ew[0] == q:
                return 3
        # 翻译（英文翻译）首字母
        # 这里假设翻译和原文英文一致（如需区分可扩展）
        # 这里只处理原文英文
        # 其他位置
        for ew in english_words:
            if q in ew:
                return 2
        return 0

    def search(self, query, top_n=5):
        try:
            start_time = time.time()
            if self._is_english(query):
                from_lang = 'en'
                translated_query = self._baidu_translate(query, 'en', 'zh')
                combined_query = f"{query} {translated_query}"
            else:
                from_lang = 'zh'
                translated_query = self._baidu_translate(query, 'zh', 'en')
                combined_query = f"{query} {translated_query}"
            query_vec = self._enhanced_query_processing(query, from_lang)
            results = []
            for content_id, content in self.content_vectors.items():
                sim = cosine_similarity(
                    query_vec.reshape(1, -1),
                    content['vector'].reshape(1, -1)
                )[0][0]
                match_source = self._get_match_source(query, self.content_data[content_id], from_lang)
                p_priority = self._p_letter_priority(query, self.content_data[content_id])
                if p_priority == 4:
                    sim += 10000
                    match_source = "原文英文首字母优先匹配"
                elif p_priority == 3:
                    sim += 1000
                    match_source = "原文英文其他位置首字母优先匹配"
                elif p_priority == 2:
                    sim += 100
                    match_source = "原文英文包含字母优先匹配"
                else:
                    substring_priority = self._substring_priority(query, self.content_data[content_id], from_lang)
                    if substring_priority >= 2:
                        sim += 10
                        match_source = "顺序子串优先匹配"
                    elif substring_priority == 1:
                        sim += 1
                        match_source = "乱序子集匹配"
                results.append({
                    'content_id': content_id,
                    'chinese': self.content_data[content_id]['chinese'],
                    'english': self.content_data[content_id]['english'],
                    'score': round(float(sim), 4),
                    'match_source': match_source,
                    'p_priority': p_priority
                })
            results.sort(key=lambda x: (-x['p_priority'], -x['score']))
            cache_stats = f"缓存命中: {self.cache_hits}次, 缓存未命中: {self.cache_misses}次"
            result_data = {
                'success': True,
                'query': query,
                'translated_query': translated_query,
                'results': results[:top_n],
                'cache_stats': cache_stats,
                'time_cost': round(time.time() - start_time, 2)
            }
            self.add_search_history(query, result_data)
            return result_data
        except Exception as e:
            error_data = {
                'success': False,
                'error': str(e),
                'suggestion': "请检查输入内容"
            }
            self.add_search_history(query, error_data)
            return error_data
    
    def _enhanced_query_processing(self, query, from_lang):
        """增强查询处理，特别是短查询和部分匹配"""
        # 短查询处理
        if len(query) < 3:
            return self._short_query_vector(query)
            
        # 正常查询处理
        if self._is_english(query):
            translated_query = self._baidu_translate(query, 'en', 'zh')
            combined_query = f"{query} {translated_query}"
        else:
            translated_query = self._baidu_translate(query, 'zh', 'en')
            combined_query = f"{query} {translated_query}"
            
        return self._text_to_vector(combined_query)
    
    def _short_query_vector(self, query):
        """处理短查询的向量生成"""
        # 1. 查找与查询部分匹配的单词
        matching_words = []
        
        # 查找包含查询字符串的单词
        for word in self.vocabulary:
            if query.lower() in word.lower():
                matching_words.append(word.lower())
                
        # 如果没有找到匹配单词，尝试在词向量字典中查找
        if not matching_words:
            for word in self.word_vectors:
                if query.lower() in word.lower():
                    matching_words.append(word.lower())
                    
        # 2. 获取基础形式
        base_words = set()
        for word in matching_words:
            base_form = self._get_word_base_form(word)
            base_words.add(base_form)
            # 添加所有相关词形
            if base_form in self.word_forms:
                base_words.update(self.word_forms[base_form])
                
        # 3. 如果找到匹配单词，使用它们的向量平均值
        if base_words:
            vectors = []
            for word in base_words:
                if word in self.word_vectors:
                    vectors.append(self.word_vectors[word])
                else:
                    # 为未知单词创建临时向量
                    np.random.seed(hash(word) % 2**32)
                    vectors.append(np.random.rand(self.vector_size))
                    
            if vectors:
                return np.mean(vectors, axis=0)
                
        # 4. 最后手段：使用查询本身的向量
        return self._text_to_vector(query)
    
    def _is_english(self, text):
        """改进的语言检测：只要包含英文字母就认为是英文"""
        return any(c.isalpha() and ord(c) < 128 for c in text)
    
    def _get_match_source(self, query, content_data, from_lang):
        """改进的匹配来源检测，特别处理词形变化"""
        query_lower = query.lower()
        chinese_lower = content_data['chinese'].lower()
        english_lower = content_data['english'].lower()
        
        # 检查是否精确匹配
        if from_lang == 'zh':
            if query_lower in chinese_lower:
                return '中文原文匹配'
            elif query_lower in english_lower:
                return '英文翻译匹配'
        else:
            if query_lower in english_lower:
                return '英文原文匹配'
            elif query_lower in chinese_lower:
                return '中文翻译匹配'
        
        # 检查词形变化匹配
        base_form = self._get_word_base_form(query_lower)
        if base_form != query_lower:
            # 检查基础形式是否在内容中
            if from_lang == 'zh':
                if base_form in chinese_lower:
                    return f'中文词形变化匹配 ({query}->{base_form})'
                elif base_form in english_lower:
                    return f'英文词形变化匹配 ({query}->{base_form})'
            else:
                if base_form in english_lower:
                    return f'英文词形变化匹配 ({query}->{base_form})'
                elif base_form in chinese_lower:
                    return f'中文词形变化匹配 ({query}->{base_form})'
        
        # 特殊处理中文单字匹配
        if from_lang == 'zh' and len(query) == 1:
            # 检查单字是否出现在内容中
            if query_lower in chinese_lower:
                return '中文单字匹配'
        
        # 最后，如果以上都不匹配，则返回模糊匹配
        return '模糊匹配'


# 创建GUI界面 - 原神风格
class SearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("星穹搜索")
        self.root.geometry("900x650")
        self.root.resizable(False, False)
        style = ttk.Style()
        style.theme_use("arc")
        self.bg_color = "#f4f8fb"
        self.card_color = "#ffffff"
        self.primary_color = "#3a7ca5"
        self.text_color = "#222"
        self.root.configure(bg=self.bg_color)
        self.engine = BilingualSearchEngine()

        # 顶部大标题
        self.title_frame = tk.Frame(root, bg=self.bg_color)
        self.title_frame.pack(fill=tk.X, pady=(32, 0))
        self.title_label = tk.Label(
            self.title_frame, text="星穹搜索", font=("微软雅黑", 32, "bold"),
            fg=self.primary_color, bg=self.bg_color, pady=10
        )
        self.title_label.pack()

        # 导航栏
        self.nav_frame = tk.Frame(root, bg=self.bg_color)
        self.nav_frame.pack(fill=tk.X, pady=(10, 0))
        nav_btn_style = {"font": ("微软雅黑", 13, "bold"), "bg": "#eaf4fb", "fg": self.primary_color, "bd": 0, "activebackground": "#d0e7f7", "activeforeground": self.primary_color, "cursor": "hand2", "relief": tk.FLAT, "highlightthickness": 0}
        self.search_button = tk.Button(self.nav_frame, text="搜索", command=self.show_search, **nav_btn_style)
        self.search_button.pack(side=tk.LEFT, padx=(250, 10), ipadx=16, ipady=6)
        self.hot_button = tk.Button(self.nav_frame, text="热点话题", command=self.show_hot_topics, **nav_btn_style)
        self.hot_button.pack(side=tk.LEFT, padx=10, ipadx=16, ipady=6)
        self.history_button = tk.Button(self.nav_frame, text="搜索历史", command=self.show_search_history, **nav_btn_style)
        self.history_button.pack(side=tk.LEFT, padx=10, ipadx=16, ipady=6)

        # 主内容区
        self.main_frame = tk.Frame(root, bg=self.bg_color)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=(10, 0))
        self.init_search_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def card(self, parent):
        frame = tk.Frame(parent, bg=self.card_color, bd=0, highlightthickness=0)
        frame.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)
        frame.config(highlightbackground="#e0e0e0", highlightcolor="#e0e0e0")
        return frame

    def init_search_ui(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        card_frame = self.card(self.main_frame)
        # 搜索框
        search_frame = tk.Frame(card_frame, bg=self.card_color)
        search_frame.pack(fill=tk.X, pady=(0, 24))
        search_label = tk.Label(search_frame, text="搜索内容:", font=("微软雅黑", 15), bg=self.card_color, fg=self.text_color)
        search_label.pack(side=tk.LEFT, padx=(0, 12))
        self.search_entry = ttk.Entry(search_frame, width=50, font=("微软雅黑", 15))
        self.search_entry.pack(side=tk.LEFT, padx=12, expand=True, fill=tk.X, ipady=8)
        self.search_entry.focus_set()
        self.search_button = ttk.Button(search_frame, text="搜索", command=self.perform_search, style="Accent.TButton")
        self.search_button.pack(side=tk.LEFT, ipadx=16, ipady=8)
        # 结果区
        self.result_text = scrolledtext.ScrolledText(card_frame, wrap=tk.WORD, font=("微软雅黑", 13), bg="#f8fbfd", fg=self.text_color, padx=18, pady=14, state=tk.DISABLED, relief=tk.FLAT, bd=0, height=18)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        self.root.bind('<Return>', lambda event: self.perform_search())

    def show_hot_topics(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        card_frame = self.card(self.main_frame)
        title_label = tk.Label(card_frame, text="热点话题", font=("微软雅黑", 18, "bold"), bg=self.card_color, fg=self.primary_color)
        title_label.pack(pady=(0, 24), anchor=tk.W)
        hot_topics = self.engine.get_hot_topics()
        hot_topics = dict(sorted(hot_topics.items(), key=lambda x: x[1], reverse=True)[:10])
        if not hot_topics:
            no_hot_label = tk.Label(card_frame, text="当前没有热点话题", font=("微软雅黑", 13), bg=self.card_color, fg="#888")
            no_hot_label.pack(pady=24)
            return
        scroll_frame = tk.Frame(card_frame, bg=self.card_color)
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        hot_list = tk.Text(scroll_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=("微软雅黑", 13), bg="#f8fbfd", fg=self.text_color, padx=18, pady=12, relief=tk.FLAT, bd=0, height=12)
        scrollbar.config(command=hot_list.yview)
        hot_list.pack(fill=tk.BOTH, expand=True)
        hot_list.insert(tk.END, "当前热点话题:\n\n")
        hot_list.tag_configure("hot", font=("微软雅黑", 13, "bold"), foreground="#007bff")
        hot_list.tag_configure("normal", font=("微软雅黑", 13))
        for i, (topic, count) in enumerate(hot_topics.items(), 1):
            hot_list.insert(tk.END, f"{i}. ", "normal")
            start = hot_list.index(tk.END)
            hot_list.insert(tk.END, f"{topic}", "hot")
            end = hot_list.index(tk.END)
            hot_list.insert(tk.END, f" ({count}次搜索)\n", "normal")
            tag = f"topic_{i}"
            hot_list.tag_add(tag, start, end)
            hot_list.tag_bind(tag, "<Enter>", lambda e, t=tag: hot_list.tag_configure(t, foreground="#0056b3"))
            hot_list.tag_bind(tag, "<Leave>", lambda e, t=tag: hot_list.tag_configure(t, foreground="#007bff"))
            hot_list.tag_bind(tag, "<Button-1>", lambda e, t=topic: self.search_topic(t))
        hot_list.config(state=tk.DISABLED)

    def show_search_history(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        card_frame = self.card(self.main_frame)
        title_label = tk.Label(card_frame, text="搜索历史", font=("微软雅黑", 18, "bold"), bg=self.card_color, fg=self.primary_color)
        title_label.pack(pady=(0, 24), anchor=tk.W)
        history = self.engine.get_search_history()
        history.reverse()
        if not history:
            no_history_label = tk.Label(card_frame, text="没有搜索记录", font=("微软雅黑", 13), bg=self.card_color, fg="#888")
            no_history_label.pack(pady=24)
            return
        scroll_frame = tk.Frame(card_frame, bg=self.card_color)
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        history_list = tk.Text(scroll_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=("微软雅黑", 13), bg="#f8fbfd", fg=self.text_color, padx=18, pady=12, relief=tk.FLAT, bd=0, height=12)
        scrollbar.config(command=history_list.yview)
        history_list.pack(fill=tk.BOTH, expand=True)
        history_list.insert(tk.END, "搜索历史记录:\n\n")
        history_list.tag_configure("header", font=("微软雅黑", 13, "bold"), foreground="#007bff")
        history_list.tag_configure("normal", font=("微软雅黑", 13))
        history_list.tag_configure("highlight", font=("微软雅黑", 13), foreground="#ff6600")
        for i, record in enumerate(history, 1):
            found_text = "✓" if record['found'] else "✗"
            history_list.insert(tk.END, f"{i}. [{found_text}] ", "highlight")
            start = history_list.index(tk.END)
            history_list.insert(tk.END, f"{record['query']} ", "header")
            end = history_list.index(tk.END)
            history_list.insert(tk.END, f"{record['timestamp']}\n", "normal")
            if record.get('translated_query'):
                history_list.insert(tk.END, f"   翻译查询: {record['translated_query']}\n", "normal")
            tag = f"history_{i}"
            history_list.tag_add(tag, start, end)
            history_list.tag_bind(tag, "<Enter>", lambda e, t=tag: history_list.tag_configure(t, foreground="#0056b3"))
            history_list.tag_bind(tag, "<Leave>", lambda e, t=tag: history_list.tag_configure(t, foreground="#007bff"))
            history_list.tag_bind(tag, "<Button-1>", lambda e, q=record['query']: self.search_history_query(q))
        history_list.config(state=tk.DISABLED)

    def search_topic(self, topic):
        """搜索热点话题"""
        # 回到搜索界面
        self.show_search()
        
        # 设置搜索框内容
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, topic)
        
        # 执行搜索
        self.perform_search()
    
    def search_history_query(self, query):
        """搜索历史记录中的查询"""
        # 回到搜索界面
        self.show_search()
        
        # 设置搜索框内容
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, query)
        
        # 执行搜索
        self.perform_search()
    
    def show_search(self):
        """显示搜索界面"""
        self.init_search_ui()
    
    def perform_search(self):
        """执行搜索操作"""
        query = self.search_entry.get().strip()
        if not query:
            return
            
        # 清空结果区域
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        
        # 添加搜索提示
        self.result_text.insert(tk.END, f"搜索中: '{query}'...\n")
        self.result_text.config(state=tk.DISABLED)
        self.root.update()
        
        # 执行搜索
        result = self.engine.search(query)
        
        # 显示结果
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        
        if result['success']:
            self.result_text.insert(tk.END, f"搜索: '{query}'\n", "highlight")
            if result.get('translated_query'):
                self.result_text.insert(tk.END, f"翻译查询: '{result['translated_query']}'\n\n", "normal")
            
            if result['results']:
                self.result_text.insert(tk.END, "搜索结果:\n\n", "header")
                for i, item in enumerate(result['results'], 1):
                    # 设置分数颜色
                    score_color = "#ff6600" if item['score'] > 0.5 else "#333333"
                    self.result_text.tag_configure(f"score_{i}", foreground=score_color)
                    
                    self.result_text.insert(tk.END, f"{i}. ", "normal")
                    self.result_text.insert(tk.END, f"[相似度: {item['score']:.4f} | {item['match_source']}]\n", f"score_{i}")
                    self.result_text.insert(tk.END, f"   中文: {item['chinese']}\n", "normal")
                    self.result_text.insert(tk.END, f"   英文: {item['english']}\n\n", "normal")
            else:
                self.result_text.insert(tk.END, "\n未找到匹配结果\n", "highlight")
            
            self.result_text.insert(tk.END, f"\n统计: {result['cache_stats']}, 耗时: {result['time_cost']}秒\n", "normal")
        else:
            self.result_text.insert(tk.END, f"搜索失败: {result['error']}\n", "highlight")
            if 'suggestion' in result:
                self.result_text.insert(tk.END, f"建议: {result['suggestion']}\n", "normal")
        
        self.result_text.config(state=tk.DISABLED)
    
    def on_closing(self):
        """关闭窗口时保存缓存"""
        self.engine._save_cache()
        self.root.destroy()


# 主程序入口
if __name__ == "__main__":
    root = ThemedTk(theme="arc")
    app = SearchApp(root)
    root.mainloop()