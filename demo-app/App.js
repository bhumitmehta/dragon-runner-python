/**
 * BuggyDemo App - A demo app for AI Testing Agent
 * Toggle "Bug Mode" to introduce bugs for the AI to find
 */

import React, { useState } from 'react';
import CalculatorScreen from './CalculatorScreen';
import LoginScreen from './LoginScreen';
import ProductsScreen from './ProductsScreen';
import CartScreen from './CartScreen';
import ContactFormScreen from './ContactFormScreen';
import {
  SafeAreaView,
  ScrollView,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Switch,
  StyleSheet,
  Alert,
  Modal,
} from 'react-native';

const App = () => {
  // Bug mode toggle
  const [bugMode, setBugMode] = useState(false);
  
  // Form state
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [cartItems, setCartItems] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [currentScreen, setCurrentScreen] = useState('home');

  // Products
  const products = [
    { id: 1, name: 'Laptop', price: 999.99 },
    { id: 2, name: 'Phone', price: 699.99 },
    { id: 3, name: 'Headphones', price: 199.99 },
    { id: 4, name: 'Tablet', price: 449.99 },
  ];

  // Calculate total - BUG: wrong calculation in bug mode
  const calculateTotal = () => {
    const total = cartItems.reduce((sum, item) => sum + item.price * item.qty, 0);
    if (bugMode) {
      return (total * 1.5).toFixed(2); // BUG: Overcharges by 50%
    }
    return total.toFixed(2);
  };

  // Login handler
  const handleLogin = () => {
    if (bugMode) {
      // BUG: Accepts any password
      if (username.length > 0) {
        setIsLoggedIn(true);
        Alert.alert('Success', 'Logged in!'); // BUG: Shows success even with wrong password
      }
    } else {
      if (username === 'demo' && password === 'password123') {
        setIsLoggedIn(true);
        Alert.alert('Success', 'Logged in successfully!');
      } else {
        Alert.alert('Error', 'Invalid credentials. Use demo/password123');
      }
    }
  };

  // Email validation - BUG: broken validation in bug mode
  const validateEmail = (email) => {
    if (bugMode) {
      return true; // BUG: Accepts any email format
    }
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  };

  // Add to cart
  const addToCart = (product) => {
    const existing = cartItems.find(item => item.id === product.id);
    if (existing) {
      setCartItems(cartItems.map(item =>
        item.id === product.id ? { ...item, qty: item.qty + quantity } : item
      ));
    } else {
      setCartItems([...cartItems, { ...product, qty: quantity }]);
    }
    
    if (bugMode) {
      // BUG: No confirmation in bug mode
    } else {
      Alert.alert('Added', `${product.name} added to cart`);
    }
  };

  // Remove from cart
  const removeFromCart = (productId) => {
    if (bugMode) {
      // BUG: Removes wrong item (first item instead of selected)
      setCartItems(cartItems.slice(1));
    } else {
      setCartItems(cartItems.filter(item => item.id !== productId));
    }
  };

  // Render Home Screen
  const renderHome = () => (
    <View style={styles.screen}>
      <Text style={styles.title} accessibilityLabel="home-title">
        Welcome to BuggyDemo
      </Text>
      
      {/* Bug Mode Toggle */}
      <View style={styles.bugToggle}>
        <Text style={styles.bugLabel}>🐛 Bug Mode:</Text>
        <Switch
          value={bugMode}
          onValueChange={setBugMode}
          accessibilityLabel="bug-mode-toggle"
          trackColor={{ false: '#767577', true: '#ff6b6b' }}
        />
        <Text style={[styles.bugStatus, bugMode && styles.bugActive]}>
          {bugMode ? 'ON' : 'OFF'}
        </Text>
      </View>

      {bugMode && (
        <View style={styles.bugWarning}>
          <Text style={styles.bugWarningText}>
            ⚠️ Bug Mode Active - App contains intentional bugs
          </Text>
        </View>
      )}

      {/* Navigation Buttons */}
      <TouchableOpacity
        style={styles.navButton}
        onPress={() => setCurrentScreen('login')}
        accessibilityLabel="go-to-login"
      >
        <Text style={styles.navButtonText}>
          {isLoggedIn ? '👤 Profile' : '🔐 Login'}
        </Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.navButton}
        onPress={() => setCurrentScreen('products')}
        accessibilityLabel="go-to-products"
      >
        <Text style={styles.navButtonText}>🛍️ Products</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.navButton}
        onPress={() => setCurrentScreen('cart')}
        accessibilityLabel="go-to-cart"
      >
        <Text style={styles.navButtonText}>
          🛒 Cart ({cartItems.length})
        </Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.navButton}
        onPress={() => setCurrentScreen('calculator')}
        accessibilityLabel="go-to-calculator"
      >
        <Text style={styles.navButtonText}>🧮 Calculator</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.navButton}
        onPress={() => setCurrentScreen('form')}
        accessibilityLabel="go-to-form"
      >
        <Text style={styles.navButtonText}>📝 Contact Form</Text>
      </TouchableOpacity>
    </View>
  );

  // Render Login Screen (modular)
  const renderLogin = () => (
    <LoginScreen
      isLoggedIn={isLoggedIn}
      username={username}
      password={password}
      setUsername={setUsername}
      setPassword={setPassword}
      handleLogin={handleLogin}
      setIsLoggedIn={setIsLoggedIn}
      styles={styles}
      bugMode={bugMode}
      setCurrentScreen={setCurrentScreen}
    />
  );

  // Render Products Screen (modular)
  const renderProducts = () => (
    <ProductsScreen
      products={products}
      quantity={quantity}
      setQuantity={setQuantity}
      addToCart={addToCart}
      styles={styles}
      bugMode={bugMode}
      setCurrentScreen={setCurrentScreen}
      cartItems={cartItems}
    />
  );

  // Render Cart Screen (modular)
  const renderCart = () => (
    <CartScreen
      cartItems={cartItems}
      removeFromCart={removeFromCart}
      calculateTotal={calculateTotal}
      styles={styles}
      bugMode={bugMode}
      setCurrentScreen={setCurrentScreen}
      showModal={showModal}
      setShowModal={setShowModal}
      setCartItems={setCartItems}
    />
  );

  // Render Calculator Screen (modular)
  const renderCalculator = () => (
    <CalculatorScreen setCurrentScreen={setCurrentScreen} />
  );

  // Render Contact Form Screen (modular)
  const renderForm = () => (
    <ContactFormScreen
      validateEmail={validateEmail}
      styles={styles}
      bugMode={bugMode}
      setCurrentScreen={setCurrentScreen}
    />
  );

  // Main render
  return (
    <SafeAreaView style={styles.container}>
      {currentScreen === 'home' && renderHome()}
      {currentScreen === 'login' && renderLogin()}
      {currentScreen === 'products' && renderProducts()}
      {currentScreen === 'cart' && renderCart()}
      {currentScreen === 'calculator' && renderCalculator()}
      {currentScreen === 'form' && renderForm()}
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  screen: {
    flex: 1,
    padding: 20,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 20,
    color: '#333',
  },
  bugToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 15,
    padding: 10,
    backgroundColor: '#fff',
    borderRadius: 10,
  },
  bugLabel: {
    fontSize: 16,
    marginRight: 10,
  },
  bugStatus: {
    fontSize: 16,
    fontWeight: 'bold',
    marginLeft: 10,
    color: '#4CAF50',
  },
  bugActive: {
    color: '#f44336',
  },
  bugWarning: {
    backgroundColor: '#fff3cd',
    padding: 10,
    borderRadius: 8,
    marginBottom: 15,
  },
  bugWarningText: {
    color: '#856404',
    textAlign: 'center',
  },
  navButton: {
    backgroundColor: '#4a90d9',
    padding: 15,
    borderRadius: 10,
    marginVertical: 8,
  },
  navButtonText: {
    color: '#fff',
    fontSize: 18,
    textAlign: 'center',
  },
  input: {
    backgroundColor: '#fff',
    padding: 15,
    borderRadius: 8,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#ddd',
    fontSize: 16,
  },
  textArea: {
    height: 100,
    textAlignVertical: 'top',
  },
  loginButton: {
    backgroundColor: '#4CAF50',
    padding: 15,
    borderRadius: 8,
    marginTop: 10,
  },
  logoutButton: {
    backgroundColor: '#f44336',
    padding: 15,
    borderRadius: 8,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  backButton: {
    marginTop: 20,
    padding: 10,
  },
  backButtonText: {
    color: '#4a90d9',
    fontSize: 16,
  },
  welcomeText: {
    fontSize: 20,
    textAlign: 'center',
    marginBottom: 20,
  },
  credText: {
    textAlign: 'center',
    color: '#666',
    marginTop: 15,
  },
  hintText: {
    color: '#f44336',
    marginBottom: 10,
  },
  quantityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 15,
  },
  qtyButton: {
    backgroundColor: '#4a90d9',
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 10,
  },
  qtyButtonText: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  qtyText: {
    fontSize: 18,
    minWidth: 30,
    textAlign: 'center',
  },
  productList: {
    maxHeight: 300,
  },
  productCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#fff',
    padding: 15,
    borderRadius: 8,
    marginBottom: 10,
  },
  productName: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  productPrice: {
    fontSize: 16,
    color: '#4CAF50',
  },
  addButton: {
    backgroundColor: '#4a90d9',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
  addButtonText: {
    color: '#fff',
    fontWeight: 'bold',
  },
  cartList: {
    maxHeight: 250,
  },
  cartItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#fff',
    padding: 15,
    borderRadius: 8,
    marginBottom: 10,
  },
  cartItemName: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  cartItemDetails: {
    color: '#666',
  },
  removeButton: {
    padding: 10,
  },
  removeButtonText: {
    color: '#f44336',
    fontSize: 18,
  },
  emptyCart: {
    textAlign: 'center',
    fontSize: 16,
    color: '#666',
    marginTop: 50,
  },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: 15,
    backgroundColor: '#fff',
    borderRadius: 8,
    marginVertical: 10,
  },
  totalLabel: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  totalAmount: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#4CAF50',
  },
  checkoutButton: {
    backgroundColor: '#4CAF50',
    padding: 15,
    borderRadius: 8,
  },
  bugIndicator: {
    color: '#f44336',
    fontSize: 12,
  },
  calcButtons: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginVertical: 20,
  },
  calcButton: {
    backgroundColor: '#4a90d9',
    width: 60,
    height: 60,
    borderRadius: 30,
    justifyContent: 'center',
    alignItems: 'center',
  },
  calcButtonText: {
    color: '#fff',
    fontSize: 24,
    fontWeight: 'bold',
  },
  resultText: {
    fontSize: 24,
    textAlign: 'center',
    marginTop: 20,
  },
  charCount: {
    textAlign: 'right',
    color: '#666',
    marginBottom: 10,
  },
  validText: {
    color: '#4CAF50',
    marginBottom: 10,
  },
  submitButton: {
    backgroundColor: '#4a90d9',
    padding: 15,
    borderRadius: 8,
  },
  successText: {
    color: '#4CAF50',
    textAlign: 'center',
    marginTop: 15,
    fontSize: 16,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#fff',
    padding: 20,
    borderRadius: 10,
    width: '80%',
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    marginBottom: 15,
  },
  modalButtons: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 20,
  },
  modalCancel: {
    padding: 10,
  },
  modalConfirm: {
    backgroundColor: '#4CAF50',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
});

export default App;
